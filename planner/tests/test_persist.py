"""Plan persistence (``Plan/08-Meal-Planner/test-plan.md``, "Persistence").

``save_plan`` writes a previewed :class:`PlanResult` — the plan row, its entries, and any dish
the generator composed — atomically, and always freezes a ``profile_snapshot`` from the live
profile so the plan stays explicable after the profile is edited or deleted.
"""

from __future__ import annotations

import datetime
import random

import pytest
from django.db import IntegrityError

from meals.models import Dish
from planner.models import MealPlan, MealPlanEntry
from planner.services.compose import build_recipe_role_pools, compose_balanced_dish
from planner.services.exceptions import PlannerError
from planner.services.generate import PlanResult, generate_plan
from planner.services.persist import reroll_entry, save_plan
from recipes.models import RecipeRole

pytestmark = pytest.mark.django_db

_START = datetime.date(2026, 3, 2)


@pytest.fixture
def pool_dish(make_dish, make_recipe, add_component):
    def _make(name, *, owner):
        dish = make_dish(name, owner=owner)
        add_component(dish, make_recipe(f"{name} recipe", owner=owner))
        return dish

    return _make


@pytest.fixture
def filled_profile(pool_dish, make_profile, alice):
    for i in range(8):
        pool_dish(f"Dish {i}", owner=alice)
    return make_profile(owner=alice, source_scope="MINE")


def test_save_plan_creates_entries(filled_profile, alice):
    result = generate_plan(alice, filled_profile, seed=1, days=3, slots=["DINNER"])

    plan = save_plan(alice, result, profile=filled_profile, start_date=_START)

    assert plan.pk is not None
    assert plan.owner == alice
    assert plan.days == 3
    assert plan.seed == result.seed
    assert plan.start_date == _START
    assert plan.profile == filled_profile
    assert set(plan.entries.values_list("day_index", flat=True)) == {0, 1, 2}
    assert plan.entries.count() == 3


def test_profile_snapshot_recorded(filled_profile, make_tag, alice):
    result = generate_plan(alice, filled_profile, seed=1, days=2, slots=["DINNER"])
    plan = save_plan(alice, result, profile=filled_profile, start_date=_START)

    snapshot = dict(plan.profile_snapshot)
    assert snapshot != {}
    assert snapshot["days"] == filled_profile.days
    assert snapshot["name"] == filled_profile.name

    filled_profile.name = "Renamed"
    filled_profile.days = 5
    filled_profile.save(update_fields=["name", "days"])
    filled_profile.excluded_tags.add(make_tag("nuts"))

    plan.refresh_from_db()
    assert plan.profile_snapshot == snapshot
    assert plan.profile_snapshot["name"] != "Renamed"


def test_deleting_profile_keeps_plan(filled_profile, alice):
    result = generate_plan(alice, filled_profile, seed=1, days=2, slots=["DINNER"])
    plan = save_plan(alice, result, profile=filled_profile, start_date=_START)
    snapshot = dict(plan.profile_snapshot)

    filled_profile.delete()

    plan.refresh_from_db()
    assert plan.profile_id is None
    assert plan.profile_snapshot == snapshot
    assert plan.profile_snapshot["slots"]  # the explanation survives


def test_save_is_atomic(role_recipes_for_compose, make_profile, alice):
    """A composed dish is created inside ``save_plan``'s transaction; a later failure in the
    same call must roll it back along with the plan.
    """
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")
    composed = compose_balanced_dish(
        build_recipe_role_pools(alice, profile),
        random.Random(1),  # noqa: S311
    )
    assert composed is not None

    # Two entries claiming the same (day, slot) — the unique constraint fails on bulk_create,
    # after the composed dish row has been written.
    clashing = PlanResult(
        entries=[
            MealPlanEntry(day_index=0, slot="DINNER", dish=composed),
            MealPlanEntry(day_index=0, slot="DINNER", dish=None),
        ],
        unfilled=[],
        reasons=[],
        seed=1,
    )

    with pytest.raises(IntegrityError):
        save_plan(alice, clashing, profile=profile, start_date=_START, days=1)

    assert MealPlan.objects.count() == 0
    assert Dish.objects.filter(owner=alice).count() == 0


# --- single-slot re-roll (B2 / B3) ---------------------------------------------------


def test_reroll_never_duplicates_another_days_dish(filled_profile, alice):
    """Seeded, many iterations: a single-slot re-roll never returns a dish already used by
    another entry of the same plan (B2)."""
    result = generate_plan(alice, filled_profile, seed=3, days=4, slots=["DINNER"])
    plan = save_plan(alice, result, profile=filled_profile, start_date=_START, days=4)
    entry_ids = list(plan.entries.order_by("day_index").values_list("pk", flat=True))

    for i in range(15):
        entry = MealPlanEntry.objects.get(pk=entry_ids[i % len(entry_ids)])
        try:
            reroll_entry(plan, entry, seed=100 + i)
        except PlannerError:
            continue
        entry.refresh_from_db()
        others = set(
            plan.entries.exclude(pk=entry.pk)
            .filter(dish__isnull=False)
            .values_list("dish_id", flat=True)
        )
        assert entry.dish_id is None or entry.dish_id not in others


def test_reroll_avoids_the_current_dish(filled_profile, alice):
    """After a re-roll the dish differs — the slot's own dish is excluded from the draw (B3)."""
    result = generate_plan(alice, filled_profile, seed=5, days=3, slots=["DINNER"])
    plan = save_plan(alice, result, profile=filled_profile, start_date=_START, days=3)
    entry = plan.entries.order_by("day_index").first()
    before = entry.dish_id

    reroll_entry(plan, entry, seed=99)

    entry.refresh_from_db()
    assert entry.dish_id != before


def test_reroll_reports_when_no_alternative(pool_dish, make_profile, alice):
    """One-candidate pool: the slot keeps its dish and a ``PlannerError`` is raised — a
    re-roll never silently clears a slot (B3)."""
    dish = pool_dish("Only", owner=alice)
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="ONE_POT")
    result = generate_plan(alice, profile, seed=1, days=1, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=1)
    entry = plan.entries.get()
    assert entry.dish_id == dish.pk

    with pytest.raises(PlannerError):
        reroll_entry(plan, entry)

    entry.refresh_from_db()
    assert entry.dish_id == dish.pk


@pytest.mark.django_db(transaction=True)
def test_reroll_runs_the_generator_outside_a_write_transaction(filled_profile, alice, monkeypatch):
    """08.19 R1 — ``reroll_entry`` must build the ``PlanResult`` *before* opening its write
    transaction (ARCHITECTURE §2: "never hold a write transaction across a slow loop"). The
    generator issues its reads with the connection not in an atomic block."""
    from django.db import connection

    import planner.services.generate as generate_mod

    result = generate_plan(alice, filled_profile, seed=7, days=2, slots=["DINNER"])
    plan = save_plan(alice, result, profile=filled_profile, start_date=_START, days=2)
    entry = plan.entries.order_by("day_index").first()

    real_generate = generate_mod.generate_plan
    observed: dict[str, bool] = {}

    def spy(*args, **kwargs):
        observed["in_atomic_block"] = connection.in_atomic_block
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(generate_mod, "generate_plan", spy)
    reroll_entry(plan, entry, seed=8)

    assert observed["in_atomic_block"] is False


@pytest.fixture
def role_recipes_for_compose(make_recipe, alice):
    for role, name in (
        (RecipeRole.PROTEIN, "Chicken"),
        (RecipeRole.CARB, "Rice"),
        (RecipeRole.VEGETABLE, "Beans"),
    ):
        make_recipe(name, owner=alice, role=role)
