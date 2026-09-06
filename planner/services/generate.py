"""The seeded generator (``Plan/08-Meal-Planner/design.md``, "The generator").

``generate_plan`` fills a day/slot grid from the candidate pool using ``random.Random(seed)``
— so the same seed produces byte-identical output, which is the only thing that makes the
planner testable at all (C9). It degrades honestly: an over-constrained request comes back as
a partial plan whose every empty slot carries a human-readable reason, and it never loops —
forward progress or a bounded backtrack, capped at :data:`MAX_BACKTRACKS`.

Nothing here is persisted. ``generate_plan`` returns **unsaved** ``MealPlanEntry`` instances;
08.6 decides what to write.

The ``BALANCED``-with-no-qualifying-dish fallback (compose a dish from a protein + carb +
vegetable recipe) is 08.5. Until then :func:`_compose_balanced_dish` is a seam that returns
``None``, so the slot degrades to an explained unfilled entry rather than half-building
composition here.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from meals.models import Dish, DishStats
from meals.services.dishes import roles as dish_roles
from planner.models import DishTemplate, MealPlanEntry, MealSlot
from planner.services.candidates import build_candidate_pool, explain_empty_pool
from recipes.models import RecipeRole

if TYPE_CHECKING:
    from planner.models import MealPlanProfile

MAX_BACKTRACKS = 50

_BALANCED_ROLES = frozenset(
    {RecipeRole.PROTEIN.value, RecipeRole.CARB.value, RecipeRole.VEGETABLE.value}
)
_ONE_POT_ROLE = RecipeRole.ONE_POT.value

_GENERIC_SLOT_REASON = "No dish satisfies the constraints for this slot."


@dataclass
class PlanResult:
    """The outcome of one generation pass.

    ``entries`` has one **unsaved** ``MealPlanEntry`` per requested day/slot, in grid order —
    an unfilled slot is still an entry, with ``dish=None``. ``unfilled`` and ``reasons`` are
    parallel: ``reasons[k]`` explains ``unfilled[k]``.

    ``backtracks`` is not in ``design.md``'s dataclass sketch — it is carried for observability
    (the "backtracking is bounded" guarantee is only testable if the count is visible) and for
    a future telemetry line. Callers that persist a plan ignore it.
    """

    entries: list[MealPlanEntry]
    unfilled: list[tuple[int, str]]
    reasons: list[str]
    seed: int
    backtracks: int = 0


def generate_plan(
    user: object,
    profile: MealPlanProfile,
    *,
    seed: int,
    days: int | None = None,
    slots: Sequence[str] | None = None,
    locked: Sequence[MealPlanEntry] | None = None,
) -> PlanResult:
    """Generate a plan for ``user`` under ``profile`` with the given ``seed``.

    ``days`` / ``slots`` default to the profile's. ``locked`` entries are placed unchanged,
    still consume their tag budget, and count as used dishes — a locked chicken dish plus a
    limit of one means no *second* chicken (``design.md``, step 3).
    """
    days = days if days is not None else profile.days
    slot_names = [str(s) for s in (slots if slots is not None else profile.slots)]
    if not slot_names:
        slot_names = [MealSlot.DINNER.value]

    rng = random.Random(seed)  # noqa: S311 - deterministic, non-crypto by design (C9)

    pool = build_candidate_pool(user, profile)
    pool_by_id = {dish.pk: dish for dish in pool}
    favorite_ids = set(
        DishStats.objects.filter(
            user=user, dish_id__in=list(pool_by_id), is_favorite=True
        ).values_list("dish_id", flat=True)
    )
    # Deliberate Decimal->float: ``favorites_bias`` is a selection weight handed to
    # ``rng.choices``, not a measured quantity, so ``CLAUDE.md``'s "never float" (which guards
    # kitchen measurements against binary rounding) does not apply here.
    bias = float(profile.favorites_bias)
    template = profile.dish_template
    # ``MIX`` alternates its preferred sub-template slot by slot; the RNG picks the starting
    # phase. Consumed only for ``MIX`` so BALANCED / ONE_POT keep their exact RNG streams.
    mix_phase = rng.randrange(2) if template == DishTemplate.MIX else 0
    limits = {str(key).lower(): value for key, value in (profile.tag_limits or {}).items()}

    grid = [(day, slot) for day in range(days) for slot in slot_names]
    locked_by_cell = {
        (entry.day_index, entry.slot): entry
        for entry in (locked or [])
        if entry.day_index < days and entry.slot in slot_names
    }

    tags_by_dish = {dish.pk: {tag.name.lower() for tag in dish.tags.all()} for dish in pool}
    for entry in locked_by_cell.values():
        if entry.dish_id and entry.dish_id not in tags_by_dish:
            tags_by_dish[entry.dish_id] = {tag.name.lower() for tag in entry.dish.tags.all()}

    balanced_exists = any(_is_balanced(dish) for dish in pool)
    one_pot_exists = any(_has_one_pot(dish) for dish in pool)
    empty_pool_reason = "" if pool else explain_empty_pool(user, profile)

    assignments: dict[int, Dish | None] = {}
    tried: dict[int, set[int]] = defaultdict(set)
    reason_at: dict[int, str] = {}
    backtracks = 0

    index = 0
    while index < len(grid):
        cell = grid[index]
        if cell in locked_by_cell:
            assignments[index] = locked_by_cell[cell].dish
            index += 1
            continue

        used_ids, budget = _state_before(
            index, grid, assignments, locked_by_cell, tags_by_dish, limits
        )
        candidates = _eligible(
            pool,
            template=_slot_template(template, index, mix_phase),
            used_ids=used_ids,
            budget=budget,
            excluded=tried[index],
            tags_by_dish=tags_by_dish,
            one_pot_exists=one_pot_exists,
            strict_balanced=template == DishTemplate.BALANCED,
        )
        if candidates:
            assignments[index] = _weighted_pick(candidates, favorite_ids, bias, rng)
            index += 1
            continue

        undo = _last_undoable(index, grid, assignments, locked_by_cell)
        if undo is None or backtracks >= MAX_BACKTRACKS:
            assignments[index] = _compose_balanced_dish(user, profile, rng, template)
            if assignments[index] is None:
                reason_at[index] = empty_pool_reason or _slot_reason(
                    template, balanced_exists, budget, limits
                )
            index += 1
            continue

        tried[undo].add(assignments[undo].pk)
        for cleared in range(undo, index + 1):
            assignments.pop(cleared, None)
            reason_at.pop(cleared, None)
            if cleared != undo:
                tried[cleared].clear()
        backtracks += 1
        index = undo

    return _build_result(
        grid, assignments, locked_by_cell, reason_at, empty_pool_reason, seed, backtracks
    )


def _build_result(
    grid, assignments, locked_by_cell, reason_at, empty_pool_reason, seed, backtracks
) -> PlanResult:
    entries: list[MealPlanEntry] = []
    unfilled: list[tuple[int, str]] = []
    reasons: list[str] = []
    for index, (day, slot) in enumerate(grid):
        locked_entry = locked_by_cell.get((day, slot))
        dish = locked_entry.dish if locked_entry is not None else assignments.get(index)
        entries.append(
            MealPlanEntry(
                day_index=day,
                slot=slot,
                dish=dish,
                is_locked=locked_entry is not None,
            )
        )
        if dish is None:
            unfilled.append((day, slot))
            reasons.append(reason_at.get(index) or empty_pool_reason or _GENERIC_SLOT_REASON)
    return PlanResult(
        entries=entries, unfilled=unfilled, reasons=reasons, seed=seed, backtracks=backtracks
    )


def _state_before(
    index, grid, assignments, locked_by_cell, tags_by_dish, limits
) -> tuple[set[int], dict[str, int]]:
    """Dishes already used and the tag budget remaining, recomputed from every filled slot
    before ``index`` (locked slots included). Recomputed rather than maintained incrementally
    — the grid is tiny (<=21 slots) and a stale incremental counter is exactly the "wrong in
    the direction the user notices" bug ``test_locked_entries_consume_tag_budget`` guards.
    """
    used: set[int] = set()
    budget = dict(limits)
    for position in range(index):
        cell = grid[position]
        locked_entry = locked_by_cell.get(cell)
        dish = locked_entry.dish if locked_entry is not None else assignments.get(position)
        if dish is None:
            continue
        used.add(dish.pk)
        for tag in tags_by_dish.get(dish.pk, ()):
            if tag in budget:
                budget[tag] -= 1
    return used, budget


def _slot_template(template, index: int, mix_phase: int):
    """The template actually applied to slot ``index``.

    Non-``MIX`` templates are returned unchanged. ``MIX`` alternates per slot between a
    balanced lean and a one-pot lean, with the starting phase set by ``mix_phase``
    (``design.md`` §5: "For ``MIX``, alternate per the RNG").
    """
    if template != DishTemplate.MIX:
        return template
    return DishTemplate.BALANCED if (index + mix_phase) % 2 == 0 else DishTemplate.ONE_POT


def _eligible(
    pool,
    *,
    template,
    used_ids,
    budget,
    excluded,
    tags_by_dish,
    one_pot_exists,
    strict_balanced,
) -> list[Dish]:
    base = [
        dish
        for dish in pool
        if dish.pk not in used_ids
        and dish.pk not in excluded
        and _within_budget(dish, budget, tags_by_dish)
    ]
    if not base:
        return []
    if template == DishTemplate.BALANCED:
        preferred = [dish for dish in base if _is_balanced(dish)]
        if strict_balanced:
            # A profile set to BALANCED never falls back to a non-balanced dish: an unmet
            # BALANCED slot routes to composition (08.5) and then to an explained unfilled
            # slot, not to "close enough". Reachable now the old ``balanced_exists``
            # short-circuit is gone.
            return preferred
        # A MIX slot leaning balanced is only a preference — fall back to any dish.
        return preferred or base
    if template == DishTemplate.ONE_POT and one_pot_exists:
        preferred = [dish for dish in base if _has_one_pot(dish)]
        return preferred or base
    return base


def _within_budget(dish: Dish, budget: dict[str, int], tags_by_dish) -> bool:
    for tag in tags_by_dish.get(dish.pk, ()):
        if tag in budget and budget[tag] <= 0:
            return False
    return True


def _weighted_pick(candidates: list[Dish], favorite_ids, bias: float, rng: random.Random) -> Dish:
    ordered = sorted(candidates, key=lambda dish: dish.pk)
    weights = [bias if dish.pk in favorite_ids else 1.0 for dish in ordered]
    return rng.choices(ordered, weights=weights, k=1)[0]  # noqa: S311 - see module docstring


def _last_undoable(index, grid, assignments, locked_by_cell) -> int | None:
    for position in range(index - 1, -1, -1):
        if grid[position] in locked_by_cell:
            continue
        if assignments.get(position) is not None:
            return position
    return None


def _compose_balanced_dish(user, profile, rng, template):
    """Seam for 08.5. When ``BALANCED`` has no qualifying dish, the design composes a transient
    dish from a protein + carb + vegetable recipe. Not built in this run — returning ``None``
    lets the slot fall through to an explained unfilled entry.
    """
    return None


def _slot_reason(template, balanced_exists: bool, budget: dict[str, int], limits) -> str:
    if template == DishTemplate.BALANCED and not balanced_exists:
        return (
            "No dish in your library covers protein, carb and vegetable together, and "
            "composing one from separate recipes is not available yet."
        )
    if template == DishTemplate.BALANCED:
        return (
            "Not enough dishes covering protein, carb and vegetable to fill every slot "
            "without repeating."
        )
    if limits and any(budget.get(tag, 1) <= 0 for tag in limits):
        return "Every remaining dish is over one of this week's tag limits."
    return "Not enough distinct dishes match the constraints to fill every slot."


def _is_balanced(dish: Dish) -> bool:
    return _BALANCED_ROLES <= dish_roles(dish)


def _has_one_pot(dish: Dish) -> bool:
    return _ONE_POT_ROLE in dish_roles(dish)


__all__ = ["MAX_BACKTRACKS", "PlanResult", "generate_plan"]
