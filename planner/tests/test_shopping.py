"""Shopping-list integration (``Plan/08-Meal-Planner/test-plan.md``, "Shopping list").

08.8 is pure orchestration over task 07's ``populate_shopping_list`` — these tests prove the
orchestration end to end: every planned dish's ingredients reach the list, the week aggregates
to one line per ingredient, sub-recipe yield scaling survives the whole 05 → 06 → 07 → 08
chain, regeneration never doubles, and preview writes nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lists.models import ItemSource, List, ListItem
from lists.services import get_or_create_default_shopping_list
from planner.models import MealPlanEntry
from planner.services.shopping import generate_shopping_list, preview_shopping_list

pytestmark = pytest.mark.django_db


@pytest.fixture
def dish_of(make_dish, make_recipe, add_component, add_ingredient):
    """A one-recipe dish whose recipe uses ``ingredient`` at ``quantity`` (grams)."""

    def _make(name, ingredient, *, owner, quantity="100", servings="1"):
        dish = make_dish(name, owner=owner)
        recipe = make_recipe(f"{name} recipe", owner=owner)
        add_ingredient(recipe, ingredient, quantity)
        add_component(dish, recipe, servings=servings)
        return dish

    return _make


def _schedule(plan, dishes):
    for day, dish in enumerate(dishes):
        MealPlanEntry.objects.create(plan=plan, day_index=day, slot="DINNER", dish=dish)


def test_generates_shopping_list(make_plan, dish_of, make_ingredient, alice):
    onion = make_ingredient("Onion", owner=alice)
    beef = make_ingredient("Beef", owner=alice)
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", onion, owner=alice), dish_of("Chili", beef, owner=alice)])

    result = generate_shopping_list(plan)

    names = set(
        ListItem.objects.filter(list=plan.shopping_list).values_list("ingredient__name", flat=True)
    )
    assert names == {"Onion", "Beef"}
    assert result.added == 2


def test_creates_default_list_when_none_exists(make_plan, dish_of, make_ingredient, alice):
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", make_ingredient("Onion", owner=alice), owner=alice)])

    generate_shopping_list(plan)

    lst = List.objects.get(owner=alice, is_default_shopping_list=True)
    assert lst.name == "Shopping List"
    plan.refresh_from_db()
    assert plan.shopping_list_id == lst.pk


def test_uses_existing_default_list(make_plan, dish_of, make_ingredient, alice):
    existing = get_or_create_default_shopping_list(alice)
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", make_ingredient("Onion", owner=alice), owner=alice)])

    generate_shopping_list(plan)

    assert List.objects.filter(owner=alice, is_default_shopping_list=True).count() == 1
    plan.refresh_from_db()
    assert plan.shopping_list_id == existing.pk


def test_regeneration_does_not_duplicate(make_plan, dish_of, make_ingredient, alice):
    onion = make_ingredient("Onion", owner=alice)
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", onion, owner=alice, quantity="150")])

    def quantities():
        return list(
            ListItem.objects.filter(list=plan.shopping_list).values_list("quantity", flat=True)
        )

    generate_shopping_list(plan)
    first = quantities()
    generate_shopping_list(plan)

    assert quantities() == first
    onion_lines = ListItem.objects.filter(list=plan.shopping_list, ingredient__name="Onion")
    assert onion_lines.count() == 1


def test_manual_items_preserved(make_plan, dish_of, make_ingredient, alice):
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", make_ingredient("Onion", owner=alice), owner=alice)])
    lst = get_or_create_default_shopping_list(alice)
    ListItem.objects.create(list=lst, position=0, text="Paper towels", source=ItemSource.MANUAL)

    generate_shopping_list(plan)
    generate_shopping_list(plan)

    assert lst.items.filter(text="Paper towels", source=ItemSource.MANUAL).count() == 1


def test_staples_excluded_by_default(make_plan, dish_of, make_ingredient, alice):
    salt = make_ingredient("Salt", owner=alice, is_staple=True)
    onion = make_ingredient("Onion", owner=alice)
    plan = make_plan(owner=alice)
    dish = dish_of("Stew", onion, owner=alice)
    dish.components.first().recipe.components.create(
        ingredient=salt, quantity=Decimal("5"), unit=onion.default_unit, position=1
    )
    _schedule(plan, [dish])

    result = generate_shopping_list(plan)

    names = set(
        ListItem.objects.filter(list=plan.shopping_list).values_list("ingredient__name", flat=True)
    )
    assert names == {"Onion"}
    assert result.staples_skipped == 1


def test_preview_writes_nothing(make_plan, dish_of, make_ingredient, alice):
    onion = make_ingredient("Onion", owner=alice)
    plan = make_plan(owner=alice)
    _schedule(plan, [dish_of("Stew", onion, owner=alice)])

    preview = preview_shopping_list(plan)

    assert [line.ingredient.name for line in preview.lines] == ["Onion"]
    assert ListItem.objects.count() == 0
    assert List.objects.count() == 0
    plan.refresh_from_db()
    assert plan.shopping_list_id is None


def test_aggregates_across_week(make_plan, dish_of, make_ingredient, alice):
    onion = make_ingredient("Onion", owner=alice)
    plan = make_plan(owner=alice)
    _schedule(
        plan,
        [
            dish_of("Mon", onion, owner=alice, quantity="100"),
            dish_of("Tue", onion, owner=alice, quantity="150"),
            dish_of("Wed", onion, owner=alice, quantity="250"),
        ],
    )

    generate_shopping_list(plan)

    items = ListItem.objects.filter(list=plan.shopping_list, ingredient__name="Onion")
    assert items.count() == 1
    assert items.get().quantity == Decimal("500")


def test_subrecipe_quantities_correct_through_planner(
    make_plan,
    make_dish,
    make_recipe,
    add_component,
    add_ingredient,
    add_sub_recipe,
    make_ingredient,
    gram,
    cup,
    alice,
):
    """The integration test that proves the whole feature — a hand-computed total carried
    through sub-recipe yield scaling (05), dish ``servings`` (06), aggregation (07) and the
    planner (08).

    Tomato sauce yields 4 cups from 800 g tomato. Pasta calls for 2 cups of it (half a batch
    → 400 g tomato) plus 200 g pasta. The dish takes 2 servings of Pasta → 800 g tomato,
    400 g pasta.
    """
    tomato = make_ingredient("Tomato", owner=alice)
    pasta_ing = make_ingredient("Pasta", owner=alice)

    sauce = make_recipe(
        "Tomato sauce", owner=alice, yield_quantity=Decimal("4.000"), yield_unit=cup
    )
    add_ingredient(sauce, tomato, "800", gram)

    pasta = make_recipe("Pasta", owner=alice)
    add_ingredient(pasta, pasta_ing, "200", gram, position=0)
    add_sub_recipe(pasta, sauce, "2", cup, position=1)

    dish = make_dish("Pasta dinner", owner=alice)
    add_component(dish, pasta, servings="2")

    plan = make_plan(owner=alice)
    _schedule(plan, [dish])

    generate_shopping_list(plan)

    by_name = {
        item.ingredient.name: item
        for item in ListItem.objects.filter(list=plan.shopping_list).select_related(
            "ingredient", "unit"
        )
    }
    assert by_name["Tomato"].quantity == Decimal("800")
    assert by_name["Tomato"].unit.name == "gram"
    assert by_name["Pasta"].quantity == Decimal("400")
