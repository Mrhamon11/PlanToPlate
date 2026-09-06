"""Persist a previewed plan (``Plan/08-Meal-Planner/tasks.md`` 08.6).

``generate_plan`` / ``regenerate_plan`` return an unsaved ``PlanResult``. :func:`save_plan`
writes it — the ``MealPlan`` row, its entries, and any dish the generator *composed* (a
transient protein + carb + vegetable ``Dish``) — in **one transaction**, so a mid-write
failure leaves neither a half-plan nor an orphan composed dish (test-plan: *"A failure leaves
no plan and no composed dishes"*).

``MealPlan.profile_snapshot`` ships as ``JSONField(default=dict)``, so the model alone would
happily save an empty ``{}``. The design treats the snapshot as server-generated and required
— it is what keeps a plan explicable after its profile is edited or deleted — so this service
**always** rebuilds it from the live profile here (carried-forward review finding, 08.6).
"""

from __future__ import annotations

import datetime
import random
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from core.models import Visibility
from meals.models import Dish, DishComponent
from planner.models import MealPlan, MealPlanEntry, MealSlot
from planner.services.compose import is_composed
from planner.services.exceptions import PlannerError

if TYPE_CHECKING:
    from planner.models import MealPlanProfile
    from planner.services.generate import PlanResult

#: Upper bound for a randomly drawn reroll / regenerate seed — matches
#: ``planner.serializers.SEED_MAX`` (a signed 64-bit ``BigIntegerField``).
_SEED_CEILING = 2**63 - 1


def build_profile_snapshot(profile: MealPlanProfile) -> dict:
    """The eight gears (plus ``exclude_staples``) exactly as ``profile`` holds them now,
    JSON-safe. Names — not just ids — are stored for the exclusions so the snapshot still
    reads if the tag or ingredient is later deleted.
    """
    return {
        "profile_id": profile.pk,
        "name": profile.name,
        "days": profile.days,
        "slots": list(profile.slots),
        "dish_template": profile.dish_template,
        "source_scope": profile.source_scope,
        "tag_limits": dict(profile.tag_limits or {}),
        "excluded_tags": sorted(profile.excluded_tags.values_list("name", flat=True)),
        "excluded_ingredients": sorted(profile.excluded_ingredients.values_list("name", flat=True)),
        "no_repeat_days": profile.no_repeat_days,
        "min_rating": profile.min_rating,
        "favorites_only": profile.favorites_only,
        "favorites_bias": str(profile.favorites_bias),
        "max_total_minutes": profile.max_total_minutes,
        "exclude_staples": profile.exclude_staples,
    }


@transaction.atomic
def save_plan(
    user: object,
    result: PlanResult,
    *,
    profile: MealPlanProfile,
    start_date: datetime.date,
    name: str = "",
    days: int | None = None,
) -> MealPlan:
    """Create a ``MealPlan`` from ``result`` and return it.

    Every composed dish among the entries is turned into real ``Dish`` / ``DishComponent``
    rows, owned by ``user`` and private; two entries that composed the identical recipe trio
    share one persisted dish rather than duplicating it.
    """
    if days is None:
        days = 1 + max((entry.day_index for entry in result.entries), default=0)

    plan = MealPlan.objects.create(
        owner=user,
        name=name,
        start_date=start_date,
        days=days,
        profile=profile,
        profile_snapshot=build_profile_snapshot(profile),
        seed=result.seed,
    )

    composed_cache: dict[tuple[int, ...], Dish] = {}
    entries: list[MealPlanEntry] = []
    for entry in result.entries:
        dish = entry.dish
        if dish is not None and is_composed(dish):
            dish = _materialise_composed_dish(dish, owner=user, cache=composed_cache)
        entries.append(
            MealPlanEntry(
                plan=plan,
                day_index=entry.day_index,
                slot=entry.slot,
                dish=dish,
                is_locked=entry.is_locked,
                note=entry.note,
            )
        )
    MealPlanEntry.objects.bulk_create(entries)
    return plan


def _materialise_composed_dish(
    transient: Dish, *, owner: object, cache: dict[tuple[int, ...], Dish]
) -> Dish:
    recipes = list(transient._composed_recipes)
    key = tuple(recipe.pk for recipe in recipes)
    if key in cache:
        return cache[key]

    dish = Dish.objects.create(
        owner=owner,
        name=transient.name,
        visibility=Visibility.PRIVATE,
        notes="Auto-composed by the meal planner.",
    )
    DishComponent.objects.bulk_create(
        [
            DishComponent(dish=dish, recipe=recipe, servings=Decimal(1), position=position)
            for position, recipe in enumerate(recipes)
        ]
    )
    cache[key] = dish
    return dish


@transaction.atomic
def update_plan_in_place(
    plan: MealPlan, result: PlanResult, *, seed: int | None = None
) -> MealPlan:
    """Write a regenerated ``result`` back onto ``plan`` — the persistence partner of
    ``regenerate_plan`` (08.10 carried finding).

    Unlocked entries have their dish (and any composed dish, materialised) replaced in place;
    **locked entries are left completely untouched**, which is what preserves a user's
    ``note`` on a slot they both locked and annotated. ``save_plan`` is not reused here — it
    only ever ``create()``s a second ``MealPlan``.
    """
    if seed is not None and seed != plan.seed:
        plan.seed = seed
        plan.save(update_fields=["seed"])

    existing = {(entry.day_index, entry.slot): entry for entry in plan.entries.all()}
    composed_cache: dict[tuple[int, ...], Dish] = {}
    new_rows: list[MealPlanEntry] = []

    for entry in result.entries:
        dish = entry.dish
        if dish is not None and is_composed(dish):
            dish = _materialise_composed_dish(dish, owner=plan.owner, cache=composed_cache)
        row = existing.get((entry.day_index, entry.slot))
        if row is None:
            new_rows.append(
                MealPlanEntry(
                    plan=plan,
                    day_index=entry.day_index,
                    slot=entry.slot,
                    dish=dish,
                    is_locked=entry.is_locked,
                    note=entry.note,
                )
            )
            continue
        if row.is_locked:
            continue
        row.dish = dish
        row.note = entry.note
        row.save(update_fields=["dish", "note"])

    if new_rows:
        MealPlanEntry.objects.bulk_create(new_rows)
    return plan


@transaction.atomic
def reconcile_entries(plan: MealPlan, *, days: int, slots: Sequence[str]) -> None:
    """Bring a saved plan's entry grid back in line with a changed ``days`` (``design.md``,
    "Edge cases": *"days changed after generation: extra entries are created unfilled; removed
    days drop their entries after a confirmation"*). The confirmation is the caller's — the API
    only reaches here on an explicit ``PATCH`` of ``days``.
    """
    plan.entries.filter(day_index__gte=days).delete()
    present = {(entry.day_index, entry.slot) for entry in plan.entries.all()}
    additions = [
        MealPlanEntry(plan=plan, day_index=day, slot=slot)
        for day in range(days)
        for slot in slots
        if (day, slot) not in present
    ]
    if additions:
        MealPlanEntry.objects.bulk_create(additions)


@transaction.atomic
def reroll_entry(plan: MealPlan, entry: MealPlanEntry, *, seed: int | None = None) -> MealPlanEntry:
    """Re-roll a single slot, leaving every other entry untouched (``design.md``, "API":
    *"Re-roll one slot"*; test-plan: *"Other entries unchanged"*).

    Every other entry is pinned as ``locked`` for one generator pass, so the new dish avoids
    the week's other dishes and respects the remaining tag budget exactly as a regeneration
    would. ``seed`` defaults to a fresh random draw — a reroll is "try my luck again".
    """
    from planner.services.generate import generate_plan

    if plan.profile is None:
        raise PlannerError(
            "This plan's profile has been deleted, so its slots cannot be re-rolled."
        )

    seed = random.randrange(_SEED_CEILING) if seed is None else seed  # noqa: S311 - non-crypto
    slots = snapshot_slots(plan)
    others = [other for other in plan.entries.all() if other.pk != entry.pk]

    result = generate_plan(
        plan.owner,
        plan.profile,
        seed=seed,
        days=plan.days,
        slots=slots,
        locked=others,
    )

    match = next(
        (
            candidate
            for candidate in result.entries
            if candidate.day_index == entry.day_index and candidate.slot == entry.slot
        ),
        None,
    )
    new_dish = match.dish if match is not None else None
    if new_dish is not None and is_composed(new_dish):
        new_dish = _materialise_composed_dish(new_dish, owner=plan.owner, cache={})

    entry.dish = new_dish
    entry.is_locked = False
    entry.save(update_fields=["dish", "is_locked"])
    return entry


def snapshot_slots(plan: MealPlan) -> list[str]:
    """The meal slots a plan was generated for — from its ``profile_snapshot`` first (so it
    still resolves after the profile is edited or deleted), then the live profile, then a
    dinner-only default. Shared by ``reconcile_entries`` / ``reroll_entry`` and the plan
    serializer's ``days``-change path.
    """
    snapshot = plan.profile_snapshot or {}
    slots = snapshot.get("slots")
    if slots:
        return list(slots)
    if plan.profile is not None:
        return list(plan.profile.slots)
    return [MealSlot.DINNER.value]


__all__ = [
    "build_profile_snapshot",
    "reconcile_entries",
    "reroll_entry",
    "save_plan",
    "snapshot_slots",
    "update_plan_in_place",
]
