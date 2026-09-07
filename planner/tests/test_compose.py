"""Dish composition (``Plan/08-Meal-Planner/test-plan.md``, "Composition").

When a ``BALANCED`` slot has no role-complete dish, the generator composes a transient one
from a protein + carb + vegetable recipe. It must respect the same visibility and exclusion
rules as the dish pool, degrade to an explained unfilled slot when a role is missing, and
persist **nothing** until the plan is saved.

Every test pins a seed.
"""

from __future__ import annotations

import datetime
import random

import pytest

from meals.models import Dish
from planner.models import MealPlanEntry
from planner.services.compose import (
    build_recipe_role_pools,
    compose_balanced_dish,
    composed_dish_name,
)
from planner.services.generate import generate_plan
from planner.services.persist import save_plan
from recipes.models import RecipeRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def role_recipes(make_recipe, add_ingredient, make_ingredient):
    """One recipe per composable role, each owned by the given user and carrying one
    ingredient (so an exclusion has something to catch).
    """

    def _make(owner, *, protein="Roast Chicken", carb="Jasmine Rice", vegetable="Green Beans"):
        recipes = {}
        for role, name in (
            (RecipeRole.PROTEIN, protein),
            (RecipeRole.CARB, carb),
            (RecipeRole.VEGETABLE, vegetable),
        ):
            recipe = make_recipe(name, owner=owner, role=role)
            add_ingredient(recipe, make_ingredient(f"{name} ingredient", owner=owner))
            recipes[role] = recipe
        return recipes

    return _make


def _composed_entries(result):
    return [e for e in result.entries if e.dish is not None and e.dish.pk is None]


def _signature(entry):
    return frozenset(r.pk for r in entry.dish._composed_recipes)


@pytest.fixture
def extra_role_recipes(make_recipe, add_ingredient, make_ingredient):
    """Add ``count`` further recipes per composable role, so several *distinct* trios can be
    composed within one plan.
    """

    def _make(owner, *, count):
        for role in (RecipeRole.PROTEIN, RecipeRole.CARB, RecipeRole.VEGETABLE):
            for i in range(count):
                recipe = make_recipe(f"{role} extra {i}", owner=owner, role=role)
                add_ingredient(recipe, make_ingredient(f"{role} extra {i} ing", owner=owner))

    return _make


def test_composes_protein_carb_vegetable(role_recipes, make_profile, alice):
    """One recipe per role → the first BALANCED slot composes the one possible trio and the
    surplus slots go **honestly unfilled** rather than repeating it (reviewer finding 1: a
    plan never repeats a dish, composed dishes included).
    """
    role_recipes(alice)
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")

    result = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])

    composed = _composed_entries(result)
    assert len(composed) == 1
    assert len(result.unfilled) == 2
    assert {r.role for r in composed[0].dish._composed_recipes} == {
        RecipeRole.PROTEIN,
        RecipeRole.CARB,
        RecipeRole.VEGETABLE,
    }


def test_composed_dishes_within_one_plan_are_distinct(
    role_recipes, extra_role_recipes, make_profile, alice
):
    """Reviewer finding 1: composed dishes must not repeat within a plan. With three recipes
    per role several trios are possible; every composed slot must carry a distinct trio, and
    the outcome is deterministic under a fixed seed.
    """
    role_recipes(alice)
    extra_role_recipes(alice, count=2)
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")

    result = generate_plan(alice, profile, seed=7, days=5, slots=["DINNER"])
    composed = _composed_entries(result)

    assert len(composed) >= 2
    signatures = [_signature(e) for e in composed]
    assert len(signatures) == len(set(signatures))

    again = generate_plan(alice, profile, seed=7, days=5, slots=["DINNER"])
    assert [(e.day_index, e.slot, e.dish.name if e.dish else None) for e in result.entries] == [
        (e.day_index, e.slot, e.dish.name if e.dish else None) for e in again.entries
    ]


def test_composed_dish_name_lists_components(role_recipes, alice):
    recipes = role_recipes(alice)
    pools = build_recipe_role_pools(alice, _Profile())
    dish = compose_balanced_dish(pools, random.Random(1))  # noqa: S311

    assert dish is not None
    assert dish.name == composed_dish_name(dish._composed_recipes)
    for recipe in recipes.values():
        assert recipe.name in dish.name


def test_composed_dish_not_persisted_on_preview(role_recipes, make_profile, alice):
    role_recipes(alice)
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")

    for seed in range(5):
        generate_plan(alice, profile, seed=seed, days=7, slots=["DINNER"])

    assert Dish.objects.count() == 0
    assert MealPlanEntry.objects.count() == 0


def test_composed_dish_persisted_on_save(role_recipes, extra_role_recipes, make_profile, alice):
    role_recipes(alice)
    extra_role_recipes(alice, count=1)  # two recipes per role → two distinct composable trios
    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")
    result = generate_plan(alice, profile, seed=1, days=2, slots=["DINNER"])
    assert len(_composed_entries(result)) == 2

    plan = save_plan(alice, result, profile=profile, start_date=datetime.date(2026, 3, 2))

    saved_dishes = Dish.objects.filter(owner=alice)
    assert saved_dishes.count() == 2
    for dish in saved_dishes:
        assert dish.components.count() == 3
    for entry in plan.entries.all():
        assert entry.dish_id is not None
        assert entry.dish.owner == alice
    # the two entries carry two different persisted dishes — no silent repeat
    assert len({e.dish_id for e in plan.entries.all()}) == 2


def test_composition_respects_exclusions(
    role_recipes, make_profile, make_ingredient, add_ingredient, make_recipe, alice
):
    recipes = role_recipes(alice)
    peanut = make_ingredient("Peanut", owner=alice)
    add_ingredient(recipes[RecipeRole.VEGETABLE], peanut, position=1)

    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")
    profile.excluded_ingredients.add(peanut)

    result = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])

    # The only vegetable recipe carries the allergen, so no dish can be composed.
    assert _composed_entries(result) == []
    assert len(result.unfilled) == 3
    assert all(result.reasons)


def test_composition_respects_visibility(role_recipes, make_profile, alice, bob):
    role_recipes(bob)  # every role recipe belongs to bob, private
    profile = make_profile(owner=alice, source_scope="PUBLIC", dish_template="BALANCED")

    result = generate_plan(alice, profile, seed=1, days=2, slots=["DINNER"])

    assert _composed_entries(result) == []
    assert len(result.unfilled) == 2


def test_composition_falls_back_when_role_missing(
    role_recipes, make_dish, make_recipe, add_component, make_profile, alice
):
    recipes = role_recipes(alice)
    recipes[RecipeRole.VEGETABLE].delete()  # no vegetable recipe anywhere

    # A non-balanced dish so the dish pool is not empty (its own reason would otherwise win).
    plain = make_dish("Plain", owner=alice)
    add_component(plain, make_recipe("Plain recipe", owner=alice))

    profile = make_profile(owner=alice, source_scope="MINE", dish_template="BALANCED")
    result = generate_plan(alice, profile, seed=1, days=2, slots=["DINNER"])

    assert _composed_entries(result) == []
    assert len(result.unfilled) == 2
    assert all("vegetable" in reason.lower() for reason in result.reasons)


def test_composition_respects_tag_limits(
    role_recipes, make_dish, make_recipe, add_component, make_profile, make_tag, alice
):
    """A composed dish counts against ``tag_limits`` the same as a real dish. The only protein
    recipe is tagged ``chicken`` and the limit is 1, so exactly one slot composes and the rest
    degrade to unfilled entries whose reason names the tag limit. Would fail if the composer
    stopped checking the budget (all three slots would compose the chicken trio).
    """
    recipes = role_recipes(alice)
    chicken = make_tag("chicken")
    recipes[RecipeRole.PROTEIN].tags.add(chicken)

    # A non-balanced dish so the dish pool is not empty (an empty-pool reason would win otherwise).
    plain = make_dish("Plain", owner=alice)
    add_component(plain, make_recipe("Plain recipe", owner=alice))

    profile = make_profile(
        owner=alice, source_scope="MINE", dish_template="BALANCED", tag_limits={"chicken": 1}
    )

    result = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])
    again = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])

    assert len(_composed_entries(result)) == 1
    assert len(result.unfilled) == 2
    assert all("limit" in reason.lower() for reason in result.reasons)

    def shape(res):
        return [
            (e.day_index, e.slot, e.dish.name if e.dish is not None else None) for e in res.entries
        ]

    assert shape(result) == shape(again)
    assert result.reasons == again.reasons


def test_compose_returns_none_when_a_role_pool_is_empty(role_recipes, alice):
    recipes = role_recipes(alice)
    recipes[RecipeRole.CARB].delete()

    pools = build_recipe_role_pools(alice, _Profile())
    assert compose_balanced_dish(pools, random.Random(1)) is None  # noqa: S311


# --- tiny stand-in so the pool/compose units can run without a real profile row -----------


class _Profile:
    """Just the attributes ``build_recipe_role_pools`` reads off a profile."""

    class _Empty:
        def values_list(self, *_args, **_kwargs):
            return []

    excluded_tags = _Empty()
    excluded_ingredients = _Empty()
