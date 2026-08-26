"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Ingredient model"."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from catalog.models import Ingredient
from core.models import OwnedModel, Visibility

pytestmark = pytest.mark.django_db


def test_ingredient_is_owned():
    assert issubclass(Ingredient, OwnedModel)
    fresh = Ingredient()
    assert fresh.visibility == Visibility.PRIVATE


def test_name_unique_per_owner_case_insensitive(make_ingredient, user_factory, gram):
    alice = user_factory(username="alice")
    make_ingredient(name="Chicken Breast", owner=alice)

    with pytest.raises(IntegrityError):
        Ingredient.objects.create(
            name="chicken breast",
            default_unit=gram,
            owner=alice,
            is_system=False,
            visibility=Visibility.PRIVATE,
        )


def test_name_whitespace_is_normalised_for_uniqueness(make_ingredient, user_factory, gram):
    alice = user_factory(username="alice")
    make_ingredient(name="Basil", owner=alice)

    with pytest.raises(IntegrityError):
        Ingredient.objects.create(
            name="  Basil  ",
            default_unit=gram,
            owner=alice,
            is_system=False,
            visibility=Visibility.PRIVATE,
        )


def test_same_name_allowed_across_owners(make_ingredient, user_factory):
    alice = user_factory(username="alice")
    bob = user_factory(username="bob")

    make_ingredient(name="Flour", owner=alice)
    bobs = make_ingredient(name="Flour", owner=bob)

    assert bobs.pk is not None
    assert Ingredient.objects.filter(name__iexact="Flour").count() == 2


def test_system_ingredient_names_unique(make_ingredient, gram):
    make_ingredient(name="Nutmeg")  # system row (owner=None) by fixture default

    with pytest.raises(IntegrityError):
        Ingredient.objects.create(
            name="NUTMEG",
            default_unit=gram,
            is_system=True,
            owner=None,
            visibility=Visibility.PUBLIC,
        )


def test_user_and_system_may_share_a_name(make_ingredient, user_factory):
    alice = user_factory(username="alice")
    make_ingredient(name="Cinnamon")  # system
    alices = make_ingredient(name="Cinnamon", owner=alice)

    assert alices.pk is not None


def test_negative_density_rejected(gram):
    ingredient = Ingredient(
        name="Bad Density",
        default_unit=gram,
        is_system=True,
        owner=None,
        density_g_per_ml=Decimal("-1.5"),
    )
    with pytest.raises(ValidationError):
        ingredient.full_clean()


def test_zero_density_rejected(gram):
    ingredient = Ingredient(
        name="Zero Density",
        default_unit=gram,
        is_system=True,
        owner=None,
        density_g_per_ml=Decimal("0"),
    )
    with pytest.raises(ValidationError):
        ingredient.full_clean()


def test_zero_density_rejected_at_db_level(gram):
    with pytest.raises(IntegrityError):
        Ingredient.objects.create(
            name="Zero Density DB",
            default_unit=gram,
            is_system=True,
            owner=None,
            density_g_per_ml=Decimal("0"),
        )


def test_staple_defaults_false():
    assert Ingredient().is_staple is False


def test_hooks_present():
    """The task 03 convention (``core/README.md``, "Does this model contain other owned
    objects?"): an ingredient is a leaf, declared with the explicit opt-out rather than a
    no-op hook override.
    """
    from core.tests.test_conventions import _owned_models_missing_hooks

    assert Ingredient.contains_owned_children is False
    assert Ingredient().share_dependencies() == []
    assert Ingredient().copy_children(Ingredient(), copier=None) is None
    # Not yet load-bearing: with no FK from another OwnedModel to Ingredient, the relation-walk
    # heuristic already returns False for it regardless of the opt-out. This assertion only
    # starts proving the opt-out works once task 05's RecipeComponent points an FK here.
    assert Ingredient not in _owned_models_missing_hooks()
