"""Shared fixtures for the planner test suite.

Mirrors ``meals/tests/conftest.py`` (pytest does not share a sibling app's ``conftest``), plus
planner-specific factories: profiles, plans, and the ``DishStats`` helpers the candidate-pool
gears read.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from catalog.models import Dimension, Ingredient, Tag, Unit
from core.models import Visibility
from meals.models import Dish, DishComponent, DishStats
from planner.models import MealPlan, MealPlanProfile, SourceScope
from recipes.models import Recipe, RecipeComponent, RecipeRole

_UNIT_SPECS = {
    "gram": ("grams", "g", Dimension.MASS, "1", ""),
    "kilogram": ("kilograms", "kg", Dimension.MASS, "1000", ""),
    "millilitre": ("millilitres", "ml", Dimension.VOLUME, "1", ""),
    "litre": ("litres", "l", Dimension.VOLUME, "1000", ""),
    "cup": ("cups", "cup", Dimension.VOLUME, "236.5882365", ""),
    "each": ("each", "ea", Dimension.COUNT, "1", "generic"),
}


@pytest.fixture
def make_unit(db):
    def _make(name: str) -> Unit:
        plural, abbrev, dimension, factor, family = _UNIT_SPECS[name]
        unit, _ = Unit.objects.get_or_create(
            name=name,
            defaults={
                "plural": plural,
                "abbrev": abbrev,
                "dimension": dimension,
                "to_base_factor": Decimal(factor),
                "count_family": family,
            },
        )
        return unit

    return _make


@pytest.fixture
def gram(make_unit) -> Unit:
    return make_unit("gram")


@pytest.fixture
def cup(make_unit) -> Unit:
    return make_unit("cup")


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def bob(user_factory):
    return user_factory(username="bob")


@pytest.fixture
def carol(user_factory):
    return user_factory(username="carol")


@pytest.fixture
def make_tag(db):
    def _make(name: str, kind: str = Tag._meta.get_field("kind").default) -> Tag:
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"kind": kind})
        return tag

    return _make


@pytest.fixture
def make_ingredient(db, gram):
    def _make(name: str = "Tomato", *, owner=None, **kwargs) -> Ingredient:
        defaults = {
            "name": name,
            "default_unit": kwargs.pop("default_unit", gram),
            "is_system": owner is None,
            "owner": owner,
            "visibility": Visibility.PRIVATE,
        }
        defaults.update(kwargs)
        ingredient = Ingredient(**defaults)
        ingredient.save()
        return ingredient

    return _make


@pytest.fixture
def make_recipe(db, alice, cup):
    def _make(
        name: str = "Recipe", *, owner=None, role: str = RecipeRole.OTHER, **kwargs
    ) -> Recipe:
        defaults = {
            "name": name,
            "instructions": "Cook it.",
            "yield_quantity": Decimal("4.000"),
            "yield_unit": kwargs.pop("yield_unit", cup),
            "owner": owner or alice,
            "role": role,
        }
        defaults.update(kwargs)
        recipe = Recipe(**defaults)
        recipe.save()
        return recipe

    return _make


@pytest.fixture
def add_ingredient(db, gram):
    def _add(
        recipe, ingredient, quantity="100", unit=None, *, position=0, note=""
    ) -> RecipeComponent:
        return RecipeComponent.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity=Decimal(str(quantity)),
            unit=unit or gram,
            position=position,
            note=note,
        )

    return _add


@pytest.fixture
def add_sub_recipe(db, cup):
    def _add(recipe, sub_recipe, quantity="1", unit=None, *, position=0) -> RecipeComponent:
        return RecipeComponent.objects.create(
            recipe=recipe,
            sub_recipe=sub_recipe,
            quantity=Decimal(str(quantity)),
            unit=unit or cup,
            position=position,
        )

    return _add


@pytest.fixture
def make_dish(db, alice):
    def _make(name: str = "Dish", *, owner=None, tags=None, **kwargs) -> Dish:
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        dish = Dish(**defaults)
        dish.save()
        if tags:
            dish.tags.set(tags)
        return dish

    return _make


@pytest.fixture
def add_component(db):
    def _add(dish, recipe, *, servings="1", position=0) -> DishComponent:
        return DishComponent.objects.create(
            dish=dish, recipe=recipe, servings=Decimal(str(servings)), position=position
        )

    return _add


@pytest.fixture
def make_balanced_dish(db, make_dish, make_recipe, add_component):
    """A dish whose three component recipes cover protein, carb and vegetable — what the
    ``BALANCED`` template looks for.
    """
    counter = {"n": 0}

    def _make(name: str | None = None, *, owner=None, tags=None, prep=0, cook=0) -> Dish:
        counter["n"] += 1
        label = name or f"Balanced {counter['n']}"
        dish = make_dish(label, owner=owner, tags=tags)
        for role in (RecipeRole.PROTEIN, RecipeRole.CARB, RecipeRole.VEGETABLE):
            recipe = make_recipe(
                f"{label} {role}",
                owner=owner or dish.owner,
                role=role,
                prep_minutes=prep,
                cook_minutes=cook,
            )
            add_component(dish, recipe)
        return dish

    return _make


@pytest.fixture
def make_profile(db, alice):
    """A permissive profile by default — the owner's own dishes, mix template, no repeats
    window, no rating/time gates. Each gear test overrides exactly what it exercises.
    """

    def _make(*, owner=None, **kwargs) -> MealPlanProfile:
        defaults = {
            "owner": owner or alice,
            "name": kwargs.pop("name", "Test profile"),
            "source_scope": SourceScope.MINE,
            "dish_template": "MIX",
            "no_repeat_days": 0,
        }
        defaults.update(kwargs)
        profile = MealPlanProfile.objects.create(**defaults)
        return profile

    return _make


@pytest.fixture
def make_plan(db, alice):
    def _make(*, owner=None, profile=None, **kwargs) -> MealPlan:
        defaults = {
            "owner": owner or alice,
            "start_date": datetime.date(2026, 1, 5),
            "days": 7,
            "seed": 1,
            "profile_snapshot": {},
            "profile": profile,
        }
        defaults.update(kwargs)
        return MealPlan.objects.create(**defaults)

    return _make


@pytest.fixture
def set_dish_stats(db):
    """Create or update the requesting user's ``DishStats`` row for a dish."""

    def _set(user, dish, *, rating=None, is_favorite=False, days_since_made=None) -> DishStats:
        last_made_at = None
        if days_since_made is not None:
            last_made_at = timezone.now() - datetime.timedelta(days=days_since_made)
        stats, _ = DishStats.objects.update_or_create(
            user=user,
            dish=dish,
            defaults={
                "rating": rating,
                "is_favorite": is_favorite,
                "last_made_at": last_made_at,
            },
        )
        return stats

    return _set
