"""Sharing & copying for dishes and books (``Plan/06-Dishes-And-RecipeBooks/test-plan.md``,
"Sharing and copying").

The task 03 machinery is proven generically in ``core/tests``; this proves ``Dish`` and
``RecipeBook`` are wired to it — the cascade reaches their real recipe children (and
transitively the sub-recipes and ingredients), and a copy is a genuinely independent snapshot.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.models import Visibility
from core.services.copying import copy_object
from core.services.sharing import SharingError, share
from meals.models import Dish, DishComponent, DishStats, RecipeBook, RecipeBookEntry
from recipes.models import Recipe, RecipeComponent

pytestmark = pytest.mark.django_db


def _recipe(owner, cup, name="R", **kw):
    defaults = dict(
        name=name, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=owner
    )
    defaults.update(kw)
    return Recipe.objects.create(**defaults)


def test_sharing_dish_cascades_to_recipes(alice, bob, cup, gram, make_ingredient):
    ingredient = make_ingredient("Alice Spice", owner=alice, visibility=Visibility.PRIVATE)
    sub = _recipe(alice, cup, "Alice Sub", visibility=Visibility.PRIVATE)
    RecipeComponent.objects.create(
        recipe=sub, ingredient=ingredient, quantity=Decimal("1"), unit=gram
    )
    main = _recipe(alice, cup, "Alice Main", visibility=Visibility.PRIVATE)
    RecipeComponent.objects.create(recipe=main, sub_recipe=sub, quantity=Decimal("1"), unit=cup)

    dish = Dish.objects.create(name="Alice Dinner", owner=alice)
    DishComponent.objects.create(dish=dish, recipe=main, servings=Decimal("1"))

    share(dish, actor=alice, users=[bob])

    assert Dish.objects.visible_to(bob).filter(pk=dish.pk).exists()
    assert Recipe.objects.visible_to(bob).filter(pk=main.pk).exists()
    assert Recipe.objects.visible_to(bob).filter(pk=sub.pk).exists()
    from catalog.models import Ingredient

    assert Ingredient.objects.visible_to(bob).filter(pk=ingredient.pk).exists()


def test_sharing_dish_with_foreign_recipe_refused(alice, bob, carol, cup):
    foreign = _recipe(carol, cup, "Carol Secret", visibility=Visibility.PRIVATE)
    dish = Dish.objects.create(name="Alice Dinner", owner=alice)
    DishComponent.objects.create(dish=dish, recipe=foreign, servings=Decimal("1"))

    with pytest.raises(SharingError) as exc:
        share(dish, actor=alice, users=[bob])

    assert "Carol Secret" in str(exc.value)
    assert not Dish.objects.visible_to(bob).filter(pk=dish.pk).exists()


def test_copying_dish_deep_copies_recipes(alice, bob, cup, make_ingredient, gram):
    recipe = _recipe(alice, cup, "Alice Recipe", visibility=Visibility.PUBLIC)
    RecipeComponent.objects.create(
        recipe=recipe,
        ingredient=make_ingredient("Tomato"),  # system ingredient, passed by reference
        quantity=Decimal("1"),
        unit=gram,
    )
    dish = Dish.objects.create(name="Alice Dish", owner=alice, visibility=Visibility.PUBLIC)
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("2"))

    copy = copy_object(dish, actor=bob)

    assert copy.owner == bob
    assert copy.visibility == Visibility.PRIVATE
    assert copy.copied_from_id == dish.pk
    copied_component = copy.components.get()
    assert copied_component.servings == Decimal("2.00")
    assert copied_component.recipe_id != recipe.pk
    assert copied_component.recipe.owner == bob


def test_copying_book_deep_copies_recipes(alice, bob, cup):
    book = RecipeBook.objects.create(name="Alice Book", owner=alice, visibility=Visibility.PUBLIC)
    for name in ("One", "Two"):
        RecipeBookEntry.objects.create(
            book=book, recipe=_recipe(alice, cup, name, visibility=Visibility.PUBLIC)
        )

    copy = copy_object(book, actor=bob)

    assert copy.entries.count() == 2
    for entry in copy.entries.all():
        assert entry.recipe.owner == bob
        assert entry.recipe.copied_from_id is not None


def test_copied_dish_has_no_stats(alice, bob, cup):
    dish = Dish.objects.create(name="D", owner=alice, visibility=Visibility.PUBLIC)
    DishComponent.objects.create(
        dish=dish, recipe=_recipe(alice, cup, visibility=Visibility.PUBLIC), servings=Decimal("1")
    )
    DishStats.objects.create(user=alice, dish=dish, rating=5, times_made=3)

    copy = copy_object(dish, actor=bob)

    assert not DishStats.objects.filter(dish=copy).exists()


def test_editing_original_recipe_does_not_affect_copied_dish(
    alice, bob, cup, gram, make_ingredient
):
    recipe = _recipe(alice, cup, "Original", visibility=Visibility.PUBLIC)
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("Tomato"), quantity=Decimal("100"), unit=gram
    )
    dish = Dish.objects.create(name="D", owner=alice, visibility=Visibility.PUBLIC)
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"))

    copy = copy_object(dish, actor=bob)

    recipe.name = "Changed"
    recipe.save()
    recipe.components.all().delete()

    copied_recipe = copy.components.get().recipe
    assert copied_recipe.name == "Original"
    assert copied_recipe.components.count() == 1
