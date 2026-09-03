"""Scaling tests (``Plan/05-Recipes/test-plan.md``, "Scaling")."""

from __future__ import annotations

from decimal import Decimal

import pytest

from recipes.models import RecipeComponent
from recipes.services.flatten import scale

pytestmark = pytest.mark.django_db


@pytest.fixture
def recipe_with_two_ingredients(make_recipe, make_ingredient, gram, cup, add_ingredient):
    recipe = make_recipe(name="Dressing")
    add_ingredient(recipe, make_ingredient("Oil"), Decimal("100"), gram, position=0)
    add_ingredient(recipe, make_ingredient("Vinegar"), Decimal("30"), gram, position=1)
    return recipe


def test_scale_multiplies_quantities(recipe_with_two_ingredients):
    scaled = scale(recipe_with_two_ingredients, Decimal("2"))

    assert sorted(c.quantity for c in scaled) == [Decimal("60"), Decimal("200")]
    assert all(isinstance(c.quantity, Decimal) for c in scaled)


def test_scale_does_not_persist(recipe_with_two_ingredients):
    originals = {c.pk: c.quantity for c in recipe_with_two_ingredients.components.all()}

    scaled = scale(recipe_with_two_ingredients, Decimal("3"))
    for component in scaled:
        assert component.pk is None

    for component in RecipeComponent.objects.filter(recipe=recipe_with_two_ingredients):
        assert component.quantity == originals[component.pk]


def test_scale_fractional_factor(recipe_with_two_ingredients):
    scaled = scale(recipe_with_two_ingredients, Decimal("0.5"))

    assert sorted(c.quantity for c in scaled) == [Decimal("15"), Decimal("50")]


def test_scale_accepts_str_and_int_factor(recipe_with_two_ingredients):
    assert sorted(c.quantity for c in scale(recipe_with_two_ingredients, "2")) == [
        Decimal("60"),
        Decimal("200"),
    ]
    assert sorted(c.quantity for c in scale(recipe_with_two_ingredients, 2)) == [
        Decimal("60"),
        Decimal("200"),
    ]


def test_scale_rejects_float_factor(recipe_with_two_ingredients):
    """Task 05 review NB2: a ``float`` factor carries binary rounding error into the scaled
    ``Decimal`` — refused at the boundary, mirroring ``catalog.services.units._as_decimal``.
    """
    with pytest.raises(TypeError):
        scale(recipe_with_two_ingredients, 0.5)
