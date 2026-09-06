"""Candidate-pool gears (``Plan/08-Meal-Planner/test-plan.md``, "Candidate pool").

One test per gear, each proving the gear actually *narrows* the pool — and the security
anchor: a dish the requester cannot see is never a candidate.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import Visibility
from planner.models import SourceScope
from planner.services.candidates import build_candidate_pool
from recipes.models import RecipeRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def dish_with_recipe(make_dish, make_recipe, add_component):
    def _make(
        name="Dish", *, owner, role=RecipeRole.OTHER, visibility=Visibility.PRIVATE, **recipe_kwargs
    ):
        dish = make_dish(name, owner=owner, visibility=visibility)
        add_component(dish, make_recipe(f"{name} recipe", owner=owner, role=role, **recipe_kwargs))
        return dish

    return _make


def _names(pool) -> set[str]:
    return {dish.name for dish in pool}


def test_pool_only_visible_dishes(dish_with_recipe, make_profile, alice, bob):
    mine = dish_with_recipe("Mine", owner=alice)
    dish_with_recipe("Theirs", owner=bob, visibility=Visibility.PRIVATE)

    profile = make_profile(owner=alice, source_scope=SourceScope.PUBLIC)
    pool = build_candidate_pool(alice, profile)

    assert _names(pool) == {"Mine"}
    assert all(dish.pk == mine.pk for dish in pool)


def test_pool_respects_source_scope_mine(dish_with_recipe, make_profile, alice, bob):
    dish_with_recipe("Mine", owner=alice)
    shared = dish_with_recipe("Shared", owner=bob, visibility=Visibility.SHARED)
    shared.shared_with.add(alice)
    dish_with_recipe("Public", owner=bob, visibility=Visibility.PUBLIC)

    profile = make_profile(owner=alice, source_scope=SourceScope.MINE)

    assert _names(build_candidate_pool(alice, profile)) == {"Mine"}


def test_pool_respects_source_scope_shared(dish_with_recipe, make_profile, alice, bob):
    dish_with_recipe("Mine", owner=alice)
    shared = dish_with_recipe("Shared", owner=bob, visibility=Visibility.SHARED)
    shared.shared_with.add(alice)
    dish_with_recipe("Public", owner=bob, visibility=Visibility.PUBLIC)

    profile = make_profile(owner=alice, source_scope=SourceScope.SHARED)

    assert _names(build_candidate_pool(alice, profile)) == {"Mine", "Shared"}


def test_pool_respects_source_scope_public(dish_with_recipe, make_profile, alice, bob):
    dish_with_recipe("Mine", owner=alice)
    dish_with_recipe("Public", owner=bob, visibility=Visibility.PUBLIC)

    profile = make_profile(owner=alice, source_scope=SourceScope.PUBLIC)

    assert _names(build_candidate_pool(alice, profile)) == {"Mine", "Public"}


def test_pool_excludes_empty_dishes(make_dish, dish_with_recipe, make_profile, alice):
    dish_with_recipe("HasRecipe", owner=alice)
    make_dish("Empty", owner=alice)

    profile = make_profile(owner=alice)

    assert _names(build_candidate_pool(alice, profile)) == {"HasRecipe"}


def test_pool_excludes_excluded_tag(dish_with_recipe, make_profile, make_tag, alice):
    dessert = make_tag("dessert")
    sweet = dish_with_recipe("Cake", owner=alice)
    sweet.tags.add(dessert)
    dish_with_recipe("Stew", owner=alice)

    profile = make_profile(owner=alice)
    profile.excluded_tags.add(dessert)

    assert _names(build_candidate_pool(alice, profile)) == {"Stew"}


def test_pool_excludes_excluded_ingredient(
    dish_with_recipe,
    make_dish,
    make_recipe,
    add_component,
    add_ingredient,
    make_ingredient,
    make_profile,
    alice,
):
    peanut = make_ingredient("Peanut", owner=alice)
    unsafe = make_dish("Satay", owner=alice)
    unsafe_recipe = make_recipe("Satay sauce", owner=alice)
    add_ingredient(unsafe_recipe, peanut)
    add_component(unsafe, unsafe_recipe)
    dish_with_recipe("Salad", owner=alice)

    profile = make_profile(owner=alice)
    profile.excluded_ingredients.add(peanut)

    assert _names(build_candidate_pool(alice, profile)) == {"Salad"}


def test_exclusion_catches_subrecipe_ingredient(
    make_dish,
    make_recipe,
    add_component,
    add_sub_recipe,
    add_ingredient,
    make_ingredient,
    make_profile,
    alice,
):
    peanut = make_ingredient("Peanut", owner=alice)
    sub = make_recipe("Peanut base", owner=alice)
    add_ingredient(sub, peanut)
    parent = make_recipe("Noodles", owner=alice)
    add_sub_recipe(parent, sub)
    dish = make_dish("Pad Thai", owner=alice)
    add_component(dish, parent)

    safe = make_dish("Rice", owner=alice)
    add_component(safe, make_recipe("Plain rice", owner=alice))

    profile = make_profile(owner=alice)
    profile.excluded_ingredients.add(peanut)

    assert _names(build_candidate_pool(alice, profile)) == {"Rice"}


def test_pool_respects_min_rating(dish_with_recipe, make_profile, set_dish_stats, alice):
    low = dish_with_recipe("Low", owner=alice)
    high = dish_with_recipe("High", owner=alice)
    dish_with_recipe("Unrated", owner=alice)
    set_dish_stats(alice, low, rating=2)
    set_dish_stats(alice, high, rating=5)

    profile = make_profile(owner=alice, min_rating=4)

    assert _names(build_candidate_pool(alice, profile)) == {"High"}


def test_min_rating_uses_requesters_stats(
    dish_with_recipe, make_profile, set_dish_stats, alice, bob
):
    dish = dish_with_recipe("Ragu", owner=alice, visibility=Visibility.PUBLIC)
    set_dish_stats(alice, dish, rating=5)
    set_dish_stats(bob, dish, rating=2)

    alice_profile = make_profile(owner=alice, min_rating=4)
    bob_profile = make_profile(owner=bob, source_scope=SourceScope.PUBLIC, min_rating=4)

    assert _names(build_candidate_pool(alice, alice_profile)) == {"Ragu"}
    assert build_candidate_pool(bob, bob_profile) == []


def test_pool_respects_favorites_only(dish_with_recipe, make_profile, set_dish_stats, alice):
    fave = dish_with_recipe("Favourite", owner=alice)
    dish_with_recipe("Meh", owner=alice)
    set_dish_stats(alice, fave, is_favorite=True)

    profile = make_profile(owner=alice, favorites_only=True)

    assert _names(build_candidate_pool(alice, profile)) == {"Favourite"}


def test_pool_respects_max_total_minutes(dish_with_recipe, make_profile, alice):
    dish_with_recipe("Quick", owner=alice, prep_minutes=10, cook_minutes=20)
    dish_with_recipe("Slow", owner=alice, prep_minutes=40, cook_minutes=40)

    profile = make_profile(owner=alice, max_total_minutes=40)

    assert _names(build_candidate_pool(alice, profile)) == {"Quick"}


def test_pool_respects_no_repeat_days(dish_with_recipe, make_profile, set_dish_stats, alice):
    recent = dish_with_recipe("Recent", owner=alice)
    old = dish_with_recipe("Old", owner=alice)
    set_dish_stats(alice, recent, days_since_made=3)
    set_dish_stats(alice, old, days_since_made=30)

    profile = make_profile(owner=alice, no_repeat_days=14)

    assert _names(build_candidate_pool(alice, profile)) == {"Old"}


def test_no_repeat_uses_requesters_last_made(
    dish_with_recipe, make_profile, set_dish_stats, alice, bob
):
    dish = dish_with_recipe("Chili", owner=alice, visibility=Visibility.PUBLIC)
    set_dish_stats(alice, dish, days_since_made=2)

    alice_profile = make_profile(owner=alice, no_repeat_days=14)
    bob_profile = make_profile(owner=bob, source_scope=SourceScope.PUBLIC, no_repeat_days=14)

    assert build_candidate_pool(alice, alice_profile) == []
    assert _names(build_candidate_pool(bob, bob_profile)) == {"Chili"}


def test_pool_query_count(
    make_dish,
    make_recipe,
    add_component,
    add_sub_recipe,
    add_ingredient,
    make_ingredient,
    make_profile,
    alice,
):
    """The pool must not fire a query per dish (or per dish's flattened ingredient set): the
    same number of queries for a 3-dish library as for a 12-dish one.
    """
    allergen = make_ingredient("Shellfish", owner=alice)
    profile = make_profile(owner=alice)
    profile.excluded_ingredients.add(allergen)

    def add_dishes(start: int, count: int) -> None:
        for i in range(start, start + count):
            dish = make_dish(f"Dish {i}", owner=alice)
            sub = make_recipe(f"Sub {i}", owner=alice)
            add_ingredient(sub, make_ingredient(f"Filler {i}", owner=alice))
            parent = make_recipe(f"Parent {i}", owner=alice)
            add_sub_recipe(parent, sub)
            add_component(dish, parent)

    add_dishes(0, 3)
    with CaptureQueriesContext(connection) as small:
        assert len(build_candidate_pool(alice, profile)) == 3

    add_dishes(3, 9)
    with CaptureQueriesContext(connection) as large:
        assert len(build_candidate_pool(alice, profile)) == 12

    assert len(large.captured_queries) == len(small.captured_queries)
    # The equality above is the real N+1 guard; this cap (observed: 10) just keeps the
    # absolute count from drifting up unnoticed.
    assert len(small.captured_queries) <= 14
