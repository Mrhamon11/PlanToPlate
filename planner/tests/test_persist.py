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
from planner.services.generate import PlanResult, generate_plan
from planner.services.persist import save_plan
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


@pytest.fixture
def role_recipes_for_compose(make_recipe, alice):
    for role, name in (
        (RecipeRole.PROTEIN, "Chicken"),
        (RecipeRole.CARB, "Rice"),
        (RecipeRole.VEGETABLE, "Beans"),
    ):
        make_recipe(name, owner=alice, role=role)
