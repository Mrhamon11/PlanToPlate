"""Item operations — check / clear / merge / reorder / add
(``Plan/07-Lists-And-Shopping/test-plan.md``, "Item operations").
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lists.models import ItemSource, ListKind
from lists.services import (
    ListError,
    add_dish_to_list,
    add_recipe_to_list,
    clear_all,
    clear_checked,
    merge_duplicate_items,
    move_item,
    reorder_items,
    set_all_checked,
    set_item_checked,
    update_item,
)

pytestmark = pytest.mark.django_db


def test_check_and_uncheck(make_list, add_item):
    lst = make_list()
    item = add_item(lst, text="milk")

    set_item_checked(item, is_checked=True)
    item.refresh_from_db()
    assert item.is_checked is True

    set_item_checked(item, is_checked=False)
    item.refresh_from_db()
    assert item.is_checked is False


def test_clear_checked_removes_only_checked(make_list, add_item):
    lst = make_list()
    add_item(lst, text="keep", position=0)
    add_item(lst, text="gone", position=1, is_checked=True)

    removed = clear_checked(lst)

    assert removed == 1
    assert [i.text for i in lst.items.all()] == ["keep"]


def test_set_all_checked_marks_every_item(make_list, add_item):
    lst = make_list()
    add_item(lst, text="a", position=0)
    add_item(lst, text="b", position=1, is_checked=True)
    add_item(lst, text="c", position=2)

    changed = set_all_checked(lst, is_checked=True)

    assert changed == 2  # only the two that were not already checked
    assert all(i.is_checked for i in lst.items.all())


def test_clear_all_empties_the_list(make_list, add_item):
    lst = make_list()
    add_item(lst, text="a", position=0, is_checked=True)
    add_item(lst, text="b", position=1)

    removed = clear_all(lst)

    assert removed == 2
    assert lst.items.count() == 0


def test_merge_duplicates_combines_same_ingredient(make_list, add_item, make_ingredient, gram):
    lst = make_list()
    flour = make_ingredient("Flour")
    add_item(lst, ingredient=flour, quantity=Decimal("200"), unit=gram, position=0)
    add_item(lst, ingredient=flour, quantity=Decimal("300"), unit=gram, position=1)

    removed = merge_duplicate_items(lst)

    assert removed == 1
    survivors = list(lst.items.all())
    assert len(survivors) == 1
    assert survivors[0].quantity == Decimal("500")


def test_merge_duplicates_converts_units(make_list, add_item, make_ingredient, gram, kilogram):
    lst = make_list()
    flour = make_ingredient("Flour")
    add_item(lst, ingredient=flour, quantity=Decimal("500"), unit=gram, position=0)
    add_item(lst, ingredient=flour, quantity=Decimal("1"), unit=kilogram, position=1)

    merge_duplicate_items(lst)

    survivor = lst.items.get()
    # 500 g + 1 kg, summed in the keeper's unit (grams)
    assert survivor.unit == gram
    assert survivor.quantity == Decimal("1500")


def test_merge_duplicates_keeps_incompatible_separate(
    make_list, add_item, make_ingredient, gram, each
):
    lst = make_list()
    egg = make_ingredient("Egg")
    add_item(lst, ingredient=egg, quantity=Decimal("100"), unit=gram, position=0)
    add_item(lst, ingredient=egg, quantity=Decimal("2"), unit=each, position=1)

    removed = merge_duplicate_items(lst)

    assert removed == 0
    assert lst.items.count() == 2


def test_merge_is_explicit_not_automatic(make_list, add_item, make_ingredient, gram):
    lst = make_list()
    milk = make_ingredient("Milk")
    add_item(lst, ingredient=milk, quantity=Decimal("500"), unit=gram, position=0)
    add_item(lst, ingredient=milk, quantity=Decimal("250"), unit=gram, position=1)

    # No merge call — the two lines coexist until the user explicitly asks.
    assert lst.items.count() == 2


def test_reorder_updates_positions(make_list, add_item):
    lst = make_list()
    a = add_item(lst, text="a", position=0)
    b = add_item(lst, text="b", position=1)
    c = add_item(lst, text="c", position=2)

    reorder_items(lst, [c.id, a.id, b.id])

    assert [i.text for i in lst.items.all()] == ["c", "a", "b"]


def test_reorder_rejects_foreign_item(make_list, add_item):
    lst = make_list()
    other = make_list("Other")
    a = add_item(lst, text="a")
    stray = add_item(other, text="stray")

    from lists.services import ListError

    with pytest.raises(ListError):
        reorder_items(lst, [a.id, stray.id])


def test_move_item_swaps_with_neighbour(make_list, add_item):
    lst = make_list()
    add_item(lst, text="a", position=0)
    b = add_item(lst, text="b", position=1)
    add_item(lst, text="c", position=2)

    move_item(lst, b, "down")
    assert [i.text for i in lst.items.all()] == ["a", "c", "b"]

    move_item(lst, b, "up")
    assert [i.text for i in lst.items.all()] == ["a", "b", "c"]


def test_move_item_is_a_noop_at_the_boundaries(make_list, add_item):
    lst = make_list()
    first = add_item(lst, text="a", position=0)
    middle = add_item(lst, text="b", position=1)
    last = add_item(lst, text="c", position=2)

    move_item(lst, first, "up")  # already at the top
    move_item(lst, last, "down")  # already at the bottom
    move_item(lst, middle, "sideways")  # unknown direction

    assert [i.text for i in lst.items.all()] == ["a", "b", "c"]


def test_add_dish_expands_to_ingredients(
    make_list, dish_with_ingredients, make_ingredient, gram, alice
):
    shopping = make_list("Shopping", owner=alice, kind=ListKind.SHOPPING)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    items = add_dish_to_list(shopping, dish, actor=alice)

    assert [i.ingredient.name for i in items] == ["Onion"]
    assert shopping.items.get().source == ItemSource.GENERATED


def test_add_dish_twice_aggregates(make_list, dish_with_ingredients, make_ingredient, gram, alice):
    shopping = make_list("Shopping", owner=alice, kind=ListKind.SHOPPING)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    add_dish_to_list(shopping, dish, actor=alice)
    add_dish_to_list(shopping, dish, actor=alice)

    onion_items = list(shopping.items.all())
    assert len(onion_items) == 1
    assert onion_items[0].quantity == Decimal("400")


def test_add_recipe_adds_recipe_reference_not_ingredients(
    make_list, make_recipe, make_ingredient, add_ingredient, gram, alice
):
    generic = make_list("Ideas", owner=alice, kind=ListKind.GENERIC)
    recipe = make_recipe("Pancakes", owner=alice)
    add_ingredient(recipe, make_ingredient("Flour"), Decimal("300"), gram)

    items = add_recipe_to_list(generic, recipe, actor=alice)

    assert len(items) == 1
    assert items[0].recipe_id == recipe.pk
    assert items[0].ingredient_id is None
    assert generic.items.get().recipe_id == recipe.pk


def test_add_dish_to_generic_list_is_a_reference(
    make_list, dish_with_ingredients, make_ingredient, gram, alice
):
    generic = make_list("Menu ideas", owner=alice, kind=ListKind.GENERIC)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    items = add_dish_to_list(generic, dish, actor=alice)

    assert len(items) == 1
    assert items[0].dish_id == dish.pk
    assert items[0].ingredient_id is None


# --- inline quantity / unit edit (07.23) ------------------------------------------------


def test_update_item_sets_quantity_and_unit(make_list, add_item, make_ingredient, gram, kilogram):
    lst = make_list()
    item = add_item(lst, ingredient=make_ingredient("Flour"), quantity=Decimal("2"), unit=gram)

    update_item(item, quantity=Decimal("1.5"), unit=kilogram)

    item.refresh_from_db()
    assert item.quantity == Decimal("1.500")
    assert item.unit == kilogram


def test_update_item_rejects_unit_without_quantity(make_list, add_item, make_ingredient, gram):
    lst = make_list()
    item = add_item(lst, ingredient=make_ingredient("Flour"), quantity=Decimal("2"), unit=gram)

    with pytest.raises(ListError):
        update_item(item, quantity=None, unit=gram)

    item.refresh_from_db()
    assert item.quantity == Decimal("2.000")


def test_update_item_allows_clearing_quantity_to_none(make_list, add_item, make_ingredient, gram):
    lst = make_list()
    item = add_item(lst, ingredient=make_ingredient("Chicken"), quantity=Decimal("2"), unit=gram)

    update_item(item, quantity=None, unit=None)

    item.refresh_from_db()
    assert item.quantity is None
    assert item.unit is None
    # The line is still valid — the ingredient reference is content enough.
    assert lst.items.filter(pk=item.pk).exists()


def test_update_item_keeps_generated_source(make_list, add_item, make_ingredient, gram, kilogram):
    lst = make_list(kind=ListKind.SHOPPING)
    item = add_item(
        lst,
        ingredient=make_ingredient("Flour"),
        quantity=Decimal("500"),
        unit=gram,
        source=ItemSource.GENERATED,
    )

    update_item(item, quantity=Decimal("1"), unit=kilogram)

    item.refresh_from_db()
    assert item.source == ItemSource.GENERATED


@pytest.mark.parametrize(
    "bad_quantity",
    [
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-3"),
        Decimal("123456789"),  # > 7 integer digits — outside max_digits=10, decimal_places=3
    ],
)
def test_update_item_rejects_non_finite_negative_or_oversized_quantity(
    make_list, add_item, make_ingredient, gram, bad_quantity
):
    lst = make_list()
    item = add_item(lst, ingredient=make_ingredient("Flour"), quantity=Decimal("2"), unit=gram)

    with pytest.raises(ListError):
        update_item(item, quantity=bad_quantity, unit=gram)

    item.refresh_from_db()
    assert item.quantity == Decimal("2.000")
    assert item.unit == gram
