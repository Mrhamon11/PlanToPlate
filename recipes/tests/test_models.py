"""Model-layer tests for task 05 (``Plan/05-Recipes/test-plan.md``, "Models")."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from core.models import OwnedModel, Visibility
from core.services.copying import copy_object
from recipes.models import Recipe, RecipeComponent, RecipeRole

pytestmark = pytest.mark.django_db


def test_recipe_is_owned(make_recipe):
    recipe = make_recipe()
    assert isinstance(recipe, OwnedModel)
    assert recipe.visibility == Visibility.PRIVATE


def test_yield_required(alice, cup):
    with pytest.raises(IntegrityError), transaction.atomic():
        Recipe.objects.create(name="No yield", instructions="x", yield_unit=cup, owner=alice)


def test_yield_zero_rejected(alice, cup):
    with pytest.raises(IntegrityError), transaction.atomic():
        Recipe.objects.create(
            name="Zero yield",
            instructions="x",
            yield_quantity=Decimal("0"),
            yield_unit=cup,
            owner=alice,
        )


def test_negative_yield_rejected(alice, cup):
    with pytest.raises(IntegrityError), transaction.atomic():
        Recipe.objects.create(
            name="Negative yield",
            instructions="x",
            yield_quantity=Decimal("-1"),
            yield_unit=cup,
            owner=alice,
        )


def test_component_requires_exactly_one_target(make_recipe, make_ingredient, gram):
    recipe = make_recipe()
    sub = make_recipe(name="Sub")
    ingredient = make_ingredient()

    with pytest.raises(IntegrityError), transaction.atomic():
        RecipeComponent.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            sub_recipe=sub,
            quantity=Decimal("1"),
            unit=gram,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        RecipeComponent.objects.create(recipe=recipe, quantity=Decimal("1"), unit=gram)


def test_components_ordered_by_position(make_recipe, make_ingredient, gram, add_ingredient):
    recipe = make_recipe()
    a = make_ingredient("Anchovy")
    b = make_ingredient("Basil")
    c = make_ingredient("Caper")
    add_ingredient(recipe, c, 1, gram, position=2)
    add_ingredient(recipe, a, 1, gram, position=0)
    add_ingredient(recipe, b, 1, gram, position=1)

    assert [comp.ingredient.name for comp in recipe.components.all()] == [
        "Anchovy",
        "Basil",
        "Caper",
    ]


def test_delete_ingredient_in_use_protected(make_recipe, make_ingredient, gram, add_ingredient):
    recipe = make_recipe()
    ingredient = make_ingredient()
    add_ingredient(recipe, ingredient, 1, gram)

    with pytest.raises(ProtectedError):
        ingredient.delete()


def test_delete_subrecipe_in_use_protected(make_recipe, cup, add_sub_recipe):
    parent = make_recipe(name="Parent")
    sub = make_recipe(name="Sub")
    add_sub_recipe(parent, sub, 1, cup)

    with pytest.raises(ProtectedError):
        sub.delete()


def test_role_defaults_to_other(make_recipe):
    assert make_recipe().role == RecipeRole.OTHER


def test_copy_children_duplicates_components_preserving_line_details(
    alice, bob, units, make_recipe, make_ingredient, add_ingredient
):
    rub = make_ingredient("House Rub", owner=alice, visibility=Visibility.PUBLIC)
    recipe = make_recipe(name="Roast", owner=alice, visibility=Visibility.PUBLIC)
    add_ingredient(recipe, rub, Decimal("1.5"), units["tablespoon"], position=0, note="rimmed")

    copy = copy_object(recipe, actor=bob)

    assert copy.owner == bob
    assert copy.pk != recipe.pk
    (component,) = copy.components.all()
    assert component.quantity == Decimal("1.5")
    assert component.unit == units["tablespoon"]
    assert component.position == 0
    assert component.note == "rimmed"


def test_copy_children_deep_copies_private_ingredients(
    alice, bob, gram, make_recipe, make_ingredient, add_ingredient
):
    rub = make_ingredient("House Rub", owner=alice, visibility=Visibility.PUBLIC)
    recipe = make_recipe(name="Roast", owner=alice, visibility=Visibility.PUBLIC)
    add_ingredient(recipe, rub, 20, gram)

    copy = copy_object(recipe, actor=bob)

    copied_ingredient = copy.components.get().ingredient
    assert copied_ingredient.pk != rub.pk
    assert copied_ingredient.owner == bob
    assert copied_ingredient.name == "House Rub"
    assert copied_ingredient.copied_from_id == rub.pk


def test_copy_children_references_system_ingredients_by_pointer(
    alice, bob, gram, make_recipe, make_ingredient, add_ingredient
):
    """A seeded catalog ingredient is immutable and nobody-owned — a copied recipe must point
    at the same row, not fork a private duplicate that breaks shopping-list aggregation
    (task 05 review finding 1).
    """
    salt = make_ingredient("Sea Salt")  # owner=None -> is_system
    assert salt.is_system
    recipe = make_recipe(name="Roast", owner=alice, visibility=Visibility.PUBLIC)
    add_ingredient(recipe, salt, 5, gram)

    copy = copy_object(recipe, actor=bob)

    assert copy.components.get().ingredient_id == salt.pk


def test_copy_children_recurses_into_subrecipes_and_owns_the_tree(
    alice, bob, gram, units, make_recipe, make_ingredient, add_ingredient, add_sub_recipe
):
    stock_ingredient = make_ingredient("Bones", owner=alice, visibility=Visibility.PUBLIC)
    gravy = make_recipe(name="Gravy", owner=alice, visibility=Visibility.PUBLIC)
    add_ingredient(gravy, stock_ingredient, 100, gram)

    roast = make_recipe(name="Roast", owner=alice, visibility=Visibility.PUBLIC)
    add_sub_recipe(roast, gravy, 1, units["cup"])

    copy = copy_object(roast, actor=bob)

    copied_sub = copy.components.get().sub_recipe
    assert copied_sub.pk != gravy.pk
    assert copied_sub.owner == bob
    assert copied_sub.copied_from_id == gravy.pk
    nested_ingredient = copied_sub.components.get().ingredient
    assert nested_ingredient.pk != stock_ingredient.pk
    assert nested_ingredient.owner == bob

    # The original tree is untouched.
    gravy.refresh_from_db()
    assert gravy.owner == alice
    assert gravy.components.get().ingredient_id == stock_ingredient.pk


def test_hooks_return_dependencies(
    make_recipe, make_ingredient, gram, cup, add_ingredient, add_sub_recipe
):
    parent = make_recipe(name="Parent")
    sub = make_recipe(name="Sub")
    tomato = make_ingredient("Tomato")
    add_ingredient(parent, tomato, 1, gram)
    add_sub_recipe(parent, sub, 1, cup, position=1)

    deps = parent.share_dependencies()

    assert tomato in deps
    assert sub in deps
