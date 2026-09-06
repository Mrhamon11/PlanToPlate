"""Shared fixtures for the lists test suite (mirrors ``meals/tests/conftest.py``).

Unit ``to_base_factor`` values match ``catalog/fixtures/units.json`` so conversions asserted
here behave exactly as the seeded catalog would.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Dimension, Ingredient, Unit
from core.models import Visibility
from lists.models import List, ListItem, ListKind
from meals.models import Dish, DishComponent
from recipes.models import Recipe, RecipeComponent

_UNIT_SPECS = {
    "gram": ("grams", "g", Dimension.MASS, "1", ""),
    "kilogram": ("kilograms", "kg", Dimension.MASS, "1000", ""),
    "millilitre": ("millilitres", "ml", Dimension.VOLUME, "1", ""),
    "litre": ("litres", "l", Dimension.VOLUME, "1000", ""),
    "cup": ("cups", "cup", Dimension.VOLUME, "236.5882365", ""),
    "each": ("each", "ea", Dimension.COUNT, "1", "generic"),
    "clove": ("cloves", "clove", Dimension.COUNT, "1", "clove"),
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
def kilogram(make_unit) -> Unit:
    return make_unit("kilogram")


@pytest.fixture
def cup(make_unit) -> Unit:
    return make_unit("cup")


@pytest.fixture
def each(make_unit) -> Unit:
    return make_unit("each")


@pytest.fixture
def clove(make_unit) -> Unit:
    return make_unit("clove")


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
    def _make(name: str = "Tomato", *, owner=None, is_staple: bool = False, **kwargs) -> Ingredient:
        defaults = {
            "name": name,
            "default_unit": kwargs.pop("default_unit", gram),
            "is_system": owner is None,
            "owner": owner,
            "visibility": Visibility.PRIVATE,
            "is_staple": is_staple,
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
def make_dish(db, alice):
    def _make(name: str = "Dish", *, owner=None, **kwargs) -> Dish:
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        dish = Dish(**defaults)
        dish.save()
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
def make_list(db, alice):
    def _make(name: str = "List", *, owner=None, kind=ListKind.GENERIC, **kwargs) -> List:
        defaults = {"name": name, "owner": owner or alice, "kind": kind}
        defaults.update(kwargs)
        lst = List(**defaults)
        lst.save()
        return lst

    return _make


@pytest.fixture
def add_item(db):
    def _add(lst, *, position=0, **kwargs) -> ListItem:
        return ListItem.objects.create(list=lst, position=position, **kwargs)

    return _add


@pytest.fixture
def dish_with_ingredients(make_dish, make_recipe, add_component, add_ingredient, make_ingredient):
    """A factory: ``dish_with_ingredients("Curry", {"Onion": (2, unit), ...}, owner=alice)``."""

    def _make(name, ingredient_specs, *, owner=None, servings="1"):
        dish = make_dish(name, owner=owner)
        recipe = make_recipe(f"{name} recipe", owner=owner)
        for position, (ing_name, (qty, unit)) in enumerate(ingredient_specs.items()):
            ingredient = ing_name if isinstance(ing_name, Ingredient) else make_ingredient(ing_name)
            add_ingredient(recipe, ingredient, qty, unit, position=position)
        add_component(dish, recipe, servings=servings)
        return dish

    return _make
