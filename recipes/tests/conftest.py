"""Shared fixtures for the recipes test suite.

Unit ``to_base_factor`` values match ``catalog/fixtures/units.json`` (and
``catalog/tests/conftest.py``), so conversions asserted here behave exactly as the seeded
catalog would perform them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Dimension, Ingredient, Tag, Unit
from core.models import Visibility
from recipes.models import Recipe, RecipeComponent

_UNIT_SPECS = {
    "gram": ("grams", "g", Dimension.MASS, "1", ""),
    "kilogram": ("kilograms", "kg", Dimension.MASS, "1000", ""),
    "milligram": ("milligrams", "mg", Dimension.MASS, "0.001", ""),
    "ounce": ("ounces", "oz", Dimension.MASS, "28.349523125", ""),
    "pound": ("pounds", "lb", Dimension.MASS, "453.59237", ""),
    "millilitre": ("millilitres", "ml", Dimension.VOLUME, "1", ""),
    "litre": ("litres", "l", Dimension.VOLUME, "1000", ""),
    "teaspoon": ("teaspoons", "tsp", Dimension.VOLUME, "4.9289215938", ""),
    "tablespoon": ("tablespoons", "tbsp", Dimension.VOLUME, "14.7867647814", ""),
    "cup": ("cups", "cup", Dimension.VOLUME, "236.5882365", ""),
    "each": ("each", "ea", Dimension.COUNT, "1", "generic"),
    "dozen": ("dozen", "dz", Dimension.COUNT, "12", "generic"),
    "clove": ("cloves", "clove", Dimension.COUNT, "1", "clove"),
    "can": ("cans", "can", Dimension.COUNT, "1", "can"),
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
def units(make_unit):
    """Every unit in ``_UNIT_SPECS``, keyed by name — convenient when a test needs several."""
    return {name: make_unit(name) for name in _UNIT_SPECS}


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
    def _make(name: str = "Recipe", *, owner=None, **kwargs) -> Recipe:
        defaults = {
            "name": name,
            "instructions": "Cook it.",
            "yield_quantity": Decimal("4.000"),
            "yield_unit": kwargs.pop("yield_unit", cup),
            "owner": owner or alice,
        }
        defaults.update(kwargs)
        recipe = Recipe(**defaults)
        recipe.save()
        return recipe

    return _make


@pytest.fixture
def make_tag(db):
    def _make(name: str, kind: str = Tag._meta.get_field("kind").default) -> Tag:
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"kind": kind})
        return tag

    return _make


@pytest.fixture
def add_ingredient(db):
    def _add(recipe, ingredient, quantity, unit, *, position=0, note="") -> RecipeComponent:
        return RecipeComponent.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity=Decimal(str(quantity)),
            unit=unit,
            position=position,
            note=note,
        )

    return _add


@pytest.fixture
def add_sub_recipe(db):
    def _add(recipe, sub_recipe, quantity, unit, *, position=0) -> RecipeComponent:
        return RecipeComponent.objects.create(
            recipe=recipe,
            sub_recipe=sub_recipe,
            quantity=Decimal(str(quantity)),
            unit=unit,
            position=position,
        )

    return _add
