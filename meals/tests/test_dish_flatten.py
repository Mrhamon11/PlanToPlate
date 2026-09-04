"""Dish flatten (``Plan/06-Dishes-And-RecipeBooks/test-plan.md``, "Dish flatten").

A dish adds nothing to the flatten algorithm — it scales each component recipe by its
``servings`` and aggregates. These tests prove that delegation is wired correctly and that
task 05's sub-recipe yield scaling still reaches through.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from meals.models import Dish
from recipes.models import RecipeComponent
from recipes.services.flatten import aggregate
from recipes.services.flatten import flatten as flatten_recipe

pytestmark = pytest.mark.django_db


def _lines_by_name(lines):
    return {line.ingredient.name: line for line in lines}


def test_flatten_single_recipe_dish(make_dish, make_recipe, make_ingredient, add_component, gram):
    recipe = make_recipe("Salsa")
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("Tomato"), quantity=Decimal("800"), unit=gram
    )
    dish = make_dish()
    add_component(dish, recipe, servings="1")

    dish_lines = _lines_by_name(dish.flatten())
    recipe_lines = _lines_by_name(aggregate(flatten_recipe(recipe)))

    assert dish_lines.keys() == recipe_lines.keys()
    assert dish_lines["Tomato"].quantity == recipe_lines["Tomato"].quantity == Decimal("800")


def test_flatten_combines_recipes(make_dish, make_recipe, make_ingredient, add_component, gram):
    tomato = make_ingredient("Tomato")
    salsa = make_recipe("Salsa")
    RecipeComponent.objects.create(
        recipe=salsa, ingredient=tomato, quantity=Decimal("300"), unit=gram
    )
    sauce = make_recipe("Sauce")
    RecipeComponent.objects.create(
        recipe=sauce, ingredient=tomato, quantity=Decimal("500"), unit=gram
    )
    dish = make_dish()
    add_component(dish, salsa)
    add_component(dish, sauce)

    lines = dish.flatten()

    tomato_lines = [line for line in lines if line.ingredient.name == "Tomato"]
    assert len(tomato_lines) == 1
    assert tomato_lines[0].quantity == Decimal("800")


def test_flatten_scales_by_servings(make_dish, make_recipe, make_ingredient, add_component, gram):
    salsa = make_recipe("Salsa")
    RecipeComponent.objects.create(
        recipe=salsa, ingredient=make_ingredient("Tomato"), quantity=Decimal("100"), unit=gram
    )
    rice = make_recipe("Rice")
    RecipeComponent.objects.create(
        recipe=rice, ingredient=make_ingredient("Rice grain"), quantity=Decimal("100"), unit=gram
    )
    dish = make_dish()
    add_component(dish, salsa, servings="2")
    add_component(dish, rice, servings="1")

    lines = _lines_by_name(dish.flatten())

    assert lines["Tomato"].quantity == Decimal("200")
    assert lines["Rice grain"].quantity == Decimal("100")


def test_flatten_with_subrecipes(make_dish, make_recipe, make_ingredient, add_component, gram, cup):
    marinara = make_recipe("Marinara", yield_quantity=Decimal("4"), yield_unit=cup)
    RecipeComponent.objects.create(
        recipe=marinara,
        ingredient=make_ingredient("Crushed Tomatoes"),
        quantity=Decimal("800"),
        unit=gram,
    )
    parm = make_recipe("Chicken Parm")
    RecipeComponent.objects.create(
        recipe=parm, sub_recipe=marinara, quantity=Decimal("1"), unit=cup
    )
    dish = make_dish()
    add_component(dish, parm, servings="2")

    lines = _lines_by_name(dish.flatten())

    # 1 cup of a 4-cup yield = 1/4 batch = 200 g; ×2 servings = 400 g
    assert lines["Crushed Tomatoes"].quantity == Decimal("400")


def test_flatten_excludes_staples_when_asked(
    make_dish, make_recipe, make_ingredient, add_component, gram
):
    recipe = make_recipe("Salsa")
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("Tomato"), quantity=Decimal("800"), unit=gram
    )
    RecipeComponent.objects.create(
        recipe=recipe,
        ingredient=make_ingredient("Salt", is_staple=True),
        quantity=Decimal("5"),
        unit=gram,
    )
    dish = make_dish()
    add_component(dish, recipe)

    assert "Salt" in _lines_by_name(dish.flatten())
    assert "Salt" not in _lines_by_name(dish.flatten(exclude_staples=True))


def test_flatten_empty_dish_returns_empty(make_dish):
    assert make_dish().flatten() == []


def test_flatten_query_count(
    make_dish,
    make_recipe,
    make_ingredient,
    add_component,
    add_sub_recipe,
    gram,
    cup,
    django_assert_max_num_queries,
):
    """A 4-recipe dish (one with a sub-recipe) stays within a bounded query count once loaded
    through ``with_component_graph()``.
    """
    dish = make_dish()
    for i in range(3):
        recipe = make_recipe(f"R{i}")
        RecipeComponent.objects.create(
            recipe=recipe, ingredient=make_ingredient(f"I{i}"), quantity=Decimal("10"), unit=gram
        )
        add_component(dish, recipe)
    sub = make_recipe("Sub", yield_quantity=Decimal("4"), yield_unit=cup)
    RecipeComponent.objects.create(
        recipe=sub, ingredient=make_ingredient("SubIng"), quantity=Decimal("100"), unit=gram
    )
    parent = make_recipe("Parent")
    add_sub_recipe(parent, sub, 1, cup)
    add_component(dish, parent)

    loaded = Dish.objects.with_component_graph().get(pk=dish.pk)

    with django_assert_max_num_queries(15):
        aggregated = loaded.flatten()

    assert {line.ingredient.name for line in aggregated} == {"I0", "I1", "I2", "SubIng"}
