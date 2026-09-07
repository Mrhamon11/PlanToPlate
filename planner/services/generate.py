"""The seeded generator (``Plan/08-Meal-Planner/design.md``, "The generator").

``generate_plan`` fills a day/slot grid from the candidate pool using ``random.Random(seed)``
— so the same seed produces byte-identical output, which is the only thing that makes the
planner testable at all (C9). It degrades honestly: an over-constrained request comes back as
a partial plan whose every empty slot carries a human-readable reason, and it never loops —
forward progress or a bounded backtrack, capped at :data:`MAX_BACKTRACKS`.

Nothing here is persisted. ``generate_plan`` returns **unsaved** ``MealPlanEntry`` instances
(and, for a composed ``BALANCED`` slot, an unsaved ``Dish`` on the entry); 08.6 decides what
to write.

When a ``BALANCED`` slot has no qualifying dish the generator composes a transient one from a
protein + carb + vegetable recipe (:mod:`planner.services.compose`). A ``MIX`` slot leaning
balanced does the same; a ``MIX`` slot leaning one-pot, and every ``ONE_POT`` slot, fall back
to any dish instead — only strict ``BALANCED`` has no dish-level fallback.
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
from planner.services.compose import (
    COMPOSED_ROLES,
    build_recipe_role_pools,
    compose_balanced_dish,
)
from planner.services.exceptions import PlannerError
from recipes.models import RecipeRole

if TYPE_CHECKING:
    from planner.models import MealPlan, MealPlanProfile

MAX_BACKTRACKS = 50

#: Upper bound for a randomly drawn regenerate seed — a signed 64-bit ``BigIntegerField``
#: (matches ``planner.serializers.SEED_MAX`` / ``persist._SEED_CEILING``).
_SEED_CEILING = 2**63 - 1

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
    exclude: Sequence[int] | None = None,
) -> PlanResult:
    """Generate a plan for ``user`` under ``profile`` with the given ``seed``.

    ``days`` / ``slots`` default to the profile's. ``locked`` entries are placed unchanged,
    still consume their tag budget, and count as used dishes — a locked chicken dish plus a
    limit of one means no *second* chicken (``design.md``, step 3).

    ``exclude`` is a set of dish ids barred from every slot of this pass — a single-slot
    re-roll passes the slot's own current dish here so the re-roll cannot simply draw it
    again (``design.md``, "``is_locked``": *"Single-slot re-roll also excludes the slot's own
    current dish"*).
    """
    days = days if days is not None else profile.days
    slot_names = [str(s) for s in (slots if slots is not None else profile.slots)]
    if not slot_names:
        slot_names = [MealSlot.DINNER.value]

    rng = random.Random(seed)  # noqa: S311 - deterministic, non-crypto by design (C9)

    exclude_ids = {int(dish_id) for dish_id in (exclude or []) if dish_id is not None}
    pool = [dish for dish in build_candidate_pool(user, profile) if dish.pk not in exclude_ids]
    pool_by_id = {dish.pk: dish for dish in pool}
    favorite_ids = set(
        DishStats.objects.filter(
            user=user, dish_id__in=list(pool_by_id), is_favorite=True
        ).values_list("dish_id", flat=True)
    )
    # ``favorites_bias`` is a selection weight handed to ``rng.choices``, never a measured
    # quantity — ``CLAUDE.md``'s "never float" guards kitchen measurements against binary
    # rounding and does not reach here. The ``float()`` is also *required*, not merely
    # tolerated: ``random.choices`` sums its weights against ``0.0`` internally and raises
    # ``TypeError`` on a ``Decimal`` (verified on CPython 3.13), so the weight list must be
    # float end to end.
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
    # Locked entries can hold a dish that never entered the pool (its rating dropped, its
    # no-repeat window is open) — fetch their tags in one batched query, not one per entry.
    missing_locked_ids = [
        entry.dish_id
        for entry in locked_by_cell.values()
        if entry.dish_id and entry.dish_id not in tags_by_dish
    ]
    if missing_locked_ids:
        for dish in Dish.objects.filter(pk__in=missing_locked_ids).prefetch_related("tags"):
            tags_by_dish[dish.pk] = {tag.name.lower() for tag in dish.tags.all()}

    balanced_exists = any(_is_balanced(dish) for dish in pool)
    one_pot_exists = any(_has_one_pot(dish) for dish in pool)
    empty_pool_reason = "" if pool else explain_empty_pool(user, profile)

    # Recipe role pools for composition are built once, lazily — a plan that never hits an
    # unfilled BALANCED slot pays nothing for them.
    role_pool_cache: dict[str, dict[str, list]] = {}

    def role_pools() -> dict[str, list]:
        if "pools" not in role_pool_cache:
            role_pool_cache["pools"] = build_recipe_role_pools(user, profile)
        return role_pool_cache["pools"]

    assignments: dict[int, Dish | None] = {}
    composed_recipe_ids: set[int] = set()
    #: Recipe-id trios currently placed as composed dishes. Passed to ``compose_balanced_dish``
    #: as ``forbidden_signatures`` so two BALANCED slots never compose the identical trio — a
    #: repeat that ``save_plan`` would collapse onto one ``Dish`` row, silently repeating a
    #: dinner (reviewer finding 1). Released for a slot cleared by a backtrack.
    composed_signatures: set[frozenset[int]] = set()
    #: slot index → (trio signature, recipe ids) of the composed dish placed there, so a
    #: backtrack that clears the slot can release both.
    composed_at: dict[int, tuple[frozenset[int], list[int]]] = {}
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
        slot_template = _slot_template(template, index, mix_phase)
        candidates = _eligible(
            pool,
            template=slot_template,
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

        if slot_template == DishTemplate.BALANCED:
            composed = compose_balanced_dish(
                role_pools(),
                rng,
                avoid_recipe_ids=composed_recipe_ids,
                forbidden_signatures=composed_signatures,
                max_total_minutes=profile.max_total_minutes,
                tag_budget=budget,
            )
            if composed is not None:
                recipe_ids = [recipe.pk for recipe in composed._composed_recipes]
                signature = frozenset(recipe_ids)
                assignments[index] = composed
                composed_recipe_ids.update(recipe_ids)
                composed_signatures.add(signature)
                composed_at[index] = (signature, recipe_ids)
                index += 1
                continue

        undo = _last_undoable(index, grid, assignments, locked_by_cell)
        if undo is None or backtracks >= MAX_BACKTRACKS:
            missing_roles: list[str] = []
            if slot_template == DishTemplate.BALANCED:
                pools = role_pools()
                missing_roles = [role for role in COMPOSED_ROLES if not pools.get(role)]
            reason_at[index] = empty_pool_reason or _slot_reason(
                slot_template, balanced_exists, budget, limits, missing_roles=missing_roles
            )
            index += 1
            continue

        # ``_last_undoable`` only ever returns a slot holding a *real* dish — a composed slot is
        # never worth backtracking past (undoing it just re-derives the same trio and burns the
        # budget; reviewer finding 1's related note). Exclude the retried dish by pk.
        tried[undo].add(assignments[undo].pk)
        for cleared in range(undo, index + 1):
            assignments.pop(cleared, None)
            reason_at.pop(cleared, None)
            released = composed_at.pop(cleared, None)
            if released is not None:
                signature, recipe_ids = released
                composed_signatures.discard(signature)
                composed_recipe_ids.difference_update(recipe_ids)
            if cleared != undo:
                tried[cleared].clear()
        backtracks += 1
        index = undo

    return _build_result(
        grid, assignments, locked_by_cell, reason_at, empty_pool_reason, seed, backtracks
    )


def regenerate_plan(plan: MealPlan, *, seed: int | None = None) -> PlanResult:
    """Re-roll a saved plan's unlocked slots.

    Locked entries are carried through unchanged and still spend their tag budget — a locked
    chicken dish plus a limit of one means the re-roll adds no *second* chicken (``design.md``,
    "``is_locked``"). ``seed`` defaults to a **fresh random draw** — "regenerate" means "same
    settings, different luck" (the 08.15 decision note; matches ``reroll_entry``). Pass an
    explicit seed to rebuild a specific week.

    The result is a fresh preview — nothing is written. Persisting it back onto ``plan`` is
    ``planner.services.persist``'s job.
    """
    if plan.profile is None:
        raise PlannerError(
            "This plan's profile has been deleted, so it cannot be regenerated. Start a new "
            "plan from a profile instead — the saved snapshot still explains this one."
        )

    # Every locked entry is carried through untouched, *including a locked-but-empty slot* (a
    # slot whose dish was deleted, then locked). Excluding empty ones would let the generator
    # fill that cell and burn a candidate / tag-budget that ``update_plan_in_place`` then
    # discards, shrinking every other slot's pool (reviewer finding).
    locked = list(plan.entries.filter(is_locked=True).select_related("dish"))
    snapshot = plan.profile_snapshot or {}
    slots = snapshot.get("slots") or list(plan.profile.slots)
    if seed is None:
        seed = random.randrange(_SEED_CEILING)  # noqa: S311 - a plan seed, not a secret (C9)
    return generate_plan(
        plan.owner,
        plan.profile,
        seed=seed,
        days=plan.days,
        slots=slots,
        locked=locked,
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
                # Carry the annotation from the locked source entry — a user who locks *and*
                # notes a slot must not lose the note when the plan is re-persisted after a
                # regenerate (08.10 carried finding). Rolled slots have no note.
                note=locked_entry.note if locked_entry is not None else "",
            )
        )
        if dish is None and locked_entry is None:
            unfilled.append((day, slot))
            reasons.append(reason_at.get(index) or empty_pool_reason or _GENERIC_SLOT_REASON)
    return PlanResult(
        entries=entries, unfilled=unfilled, reasons=reasons, seed=seed, backtracks=backtracks
    )


def _state_before(
    index, grid, assignments, locked_by_cell, tags_by_dish, limits
) -> tuple[set[int], dict[str, int]]:
    """Dishes already used and the tag budget remaining.

    Folds in **every** locked entry regardless of its grid position, plus every non-locked
    slot already filled before ``index``. A locked entry is a fixed point: its dish must count
    as used and its tags must spend budget even when it sits on a *later* day, or a
    single-slot re-roll (which locks every other entry and refills one early slot) hands back
    a dish already used further down the week (B2 / ``design.md``, "``is_locked``").

    Recomputed rather than maintained incrementally — the grid is tiny (<=21 slots) and a
    stale incremental counter is exactly the "wrong in the direction the user notices" bug
    ``test_locked_entries_consume_tag_budget`` guards.
    """
    used: set[int] = set()
    budget = dict(limits)
    for position, cell in enumerate(grid):
        locked_entry = locked_by_cell.get(cell)
        if locked_entry is not None:
            dish = locked_entry.dish
        elif position < index:
            dish = assignments.get(position)
        else:
            dish = None
        if dish is None:
            continue
        if dish.pk is not None:
            used.add(dish.pk)
        for tag in _dish_tag_names(dish, tags_by_dish):
            if tag in budget:
                budget[tag] -= 1
    return used, budget


def _dish_tag_names(dish: Dish, tags_by_dish) -> set[str] | tuple[()]:
    """Lowercased tag names for a pool dish (from the prefetched map) or a transient composed
    dish (from the union of its recipe tags, stashed on ``_composed_tags``).
    """
    composed = getattr(dish, "_composed_tags", None)
    if composed is not None:
        return composed
    return tags_by_dish.get(dish.pk, ())


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
    # ``favorites_bias`` is only bounded ``>= 0`` on the model, so a profile with
    # ``favorites_bias = 0`` and an all-favourites candidate set would sum to zero weight and
    # make ``rng.choices`` raise ``ValueError`` ("Total of weights must be greater than
    # zero"). Fall back to a uniform draw in that corner rather than 500 (08.9 carried
    # finding) — a zero bias meaning "don't prefer favourites" degrades to "no preference".
    if sum(weights) <= 0:
        weights = None
    return rng.choices(ordered, weights=weights, k=1)[0]  # noqa: S311 - see module docstring


def _last_undoable(index, grid, assignments, locked_by_cell) -> int | None:
    """The most recent slot holding a **real** dish that a backtrack could re-choose. A
    composed slot (``dish.pk is None``) is skipped — undoing it only re-derives the identical
    trio and wastes a backtrack; the slot needing help degrades to an unfilled entry instead.
    """
    for position in range(index - 1, -1, -1):
        if grid[position] in locked_by_cell:
            continue
        dish = assignments.get(position)
        if dish is not None and dish.pk is not None:
            return position
    return None


def _slot_reason(
    template,
    balanced_exists: bool,
    budget: dict[str, int],
    limits,
    *,
    missing_roles: Sequence[str] = (),
) -> str:
    over_limit = bool(limits) and any(budget.get(tag, 1) <= 0 for tag in limits)
    if template == DishTemplate.BALANCED:
        if not balanced_exists and missing_roles:
            return (
                "No dish covers protein, carb and vegetable together, and you have no "
                f"{_humanise_roles(missing_roles)} recipe to compose one."
            )
        if over_limit:
            return (
                "Every dish and every recipe trio for this slot is over one of this week's "
                "tag limits."
            )
        return (
            "Not enough dishes covering protein, carb and vegetable to fill every slot "
            "without repeating."
        )
    if over_limit:
        return "Every remaining dish is over one of this week's tag limits."
    return "Not enough distinct dishes match the constraints to fill every slot."


def _humanise_roles(roles: Sequence[str]) -> str:
    """``["PROTEIN"]`` → "protein"; ``["PROTEIN", "VEGETABLE"]`` → "protein or vegetable";
    all three → "protein, carb or vegetable"."""
    names = [role.lower() for role in roles]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} or {names[-1]}"


def _is_balanced(dish: Dish) -> bool:
    return _BALANCED_ROLES <= dish_roles(dish)


def _has_one_pot(dish: Dish) -> bool:
    return _ONE_POT_ROLE in dish_roles(dish)


__all__ = [
    "MAX_BACKTRACKS",
    "PlannerError",
    "PlanResult",
    "generate_plan",
    "regenerate_plan",
]
