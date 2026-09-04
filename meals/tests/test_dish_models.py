"""Dish model behaviour (``Plan/06-Dishes-And-RecipeBooks/test-plan.md``, "Dish models")."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from core.models import OwnedModel, UserObjectStats
from meals.models import Dish, DishComponent, DishStats
from recipes.models import RecipeStats

pytestmark = pytest.mark.django_db


def test_dish_is_owned():
    assert issubclass(Dish, OwnedModel)


def test_dishstats_and_recipestats_share_base():
    """The refactor-safety anchor: both stats models are the *same* abstract base, not two
    hand-copied models (``design.md``: "Two copies of this model is how the third one gets
    written subtly differently").
    """
    assert issubclass(RecipeStats, UserObjectStats)
    assert issubclass(DishStats, UserObjectStats)
    base_fields = {"user", "rating", "is_favorite", "times_made", "last_made_at"}
    assert base_fields <= {f.name for f in DishStats._meta.get_fields()}
    assert base_fields <= {f.name for f in RecipeStats._meta.get_fields()}


def test_servings_zero_rejected(make_dish, make_recipe):
    dish = make_dish()
    component = DishComponent(dish=dish, recipe=make_recipe(), servings=Decimal("0"))

    with pytest.raises(ValidationError):
        component.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        component.save()


def test_servings_negative_rejected(make_dish, make_recipe):
    dish = make_dish()
    component = DishComponent(dish=dish, recipe=make_recipe(), servings=Decimal("-2"))

    with pytest.raises(ValidationError):
        component.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        component.save()


def test_components_ordered(make_dish, make_recipe, add_component):
    dish = make_dish()
    add_component(dish, make_recipe("C"), position=2)
    add_component(dish, make_recipe("A"), position=0)
    add_component(dish, make_recipe("B"), position=1)

    assert [c.position for c in dish.components.all()] == [0, 1, 2]


def test_delete_recipe_in_use_protected(make_dish, make_recipe, add_component):
    dish = make_dish()
    recipe = make_recipe("Locked")
    add_component(dish, recipe)

    with pytest.raises(ProtectedError):
        recipe.delete()

    assert dish.components.count() == 1


def test_total_minutes_parallel_prep(make_dish, make_recipe, add_component):
    """Max prep + sum cook, not a naive total: prep happens in parallel, cooking stacks."""
    dish = make_dish()
    add_component(dish, make_recipe("Roast", prep_minutes=20, cook_minutes=90))
    add_component(dish, make_recipe("Salad", prep_minutes=15, cook_minutes=0))
    add_component(dish, make_recipe("Rice", prep_minutes=5, cook_minutes=20))

    # max prep = 20, sum cook = 90 + 0 + 20 = 110
    assert dish.total_minutes == 130


def test_total_minutes_empty_dish_is_zero(make_dish):
    assert make_dish().total_minutes == 0


def test_roles_returns_component_roles(make_dish, make_recipe, add_component):
    dish = make_dish()
    add_component(dish, make_recipe("P", role="PROTEIN"))
    add_component(dish, make_recipe("C", role="CARB"))
    add_component(dish, make_recipe("C2", role="CARB"))

    assert dish.roles == {"PROTEIN", "CARB"}


def test_share_dependencies_returns_recipes(make_dish, make_recipe, add_component):
    dish = make_dish()
    r1 = make_recipe("One")
    r2 = make_recipe("Two")
    add_component(dish, r1)
    add_component(dish, r2)

    assert set(dish.share_dependencies()) == {r1, r2}


def test_dishstats_unique_per_user_dish(alice, make_dish):
    dish = make_dish()
    DishStats.objects.create(user=alice, dish=dish)

    with pytest.raises(IntegrityError), transaction.atomic():
        DishStats.objects.create(user=alice, dish=dish)
