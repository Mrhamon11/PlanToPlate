"""Shared fixtures for the meals test suite (mirrors ``recipes/tests/conftest.py``).

Unit ``to_base_factor`` values match ``catalog/fixtures/units.json`` so conversions asserted
here behave exactly as the seeded catalog would.
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


@pytest.fixture
def make_tag(db):
    def _make(name: str, kind: str = Tag._meta.get_field("kind").default) -> Tag:
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"kind": kind})
        return tag

    return _make


@pytest.fixture
def make_dish(db, alice):
    from meals.models import Dish

    def _make(name: str = "Dish", *, owner=None, **kwargs) -> Dish:
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        dish = Dish(**defaults)
        dish.save()
        return dish

    return _make


@pytest.fixture
def add_component(db):
    from meals.models import DishComponent

    def _add(dish, recipe, *, servings="1", position=0) -> DishComponent:
        return DishComponent.objects.create(
            dish=dish, recipe=recipe, servings=Decimal(str(servings)), position=position
        )

    return _add


@pytest.fixture
def make_book(db, alice):
    from meals.models import RecipeBook

    def _make(name: str = "Book", *, owner=None, **kwargs) -> RecipeBook:
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        book = RecipeBook(**defaults)
        book.save()
        return book

    return _make
