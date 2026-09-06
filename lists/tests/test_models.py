"""``List`` / ``ListItem`` model behaviour (``Plan/07-Lists-And-Shopping/test-plan.md``,
"Models").
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from core.models import OwnedModel
from lists.models import ItemSource, List, ListItem, ListKind

pytestmark = pytest.mark.django_db


def test_list_is_owned(make_list, alice):
    lst = make_list("Groceries", owner=alice)
    assert isinstance(lst, OwnedModel)
    assert lst.owner == alice
    assert List.objects.visible_to(alice).filter(pk=lst.pk).exists()


def test_item_requires_some_content(make_list):
    lst = make_list()
    with pytest.raises(IntegrityError):
        ListItem.objects.create(list=lst, position=0)


def test_item_accepts_text_only(make_list):
    lst = make_list()
    item = ListItem.objects.create(list=lst, text="Batteries")
    assert item.pk is not None


def test_item_accepts_ingredient_with_quantity(make_list, make_ingredient, gram):
    lst = make_list()
    item = ListItem.objects.create(
        list=lst, ingredient=make_ingredient("Flour"), quantity=Decimal("500"), unit=gram
    )
    assert item.pk is not None


def test_item_quantity_without_unit_allowed(make_list, make_ingredient):
    lst = make_list()
    item = ListItem.objects.create(
        list=lst, ingredient=make_ingredient("Lemon"), quantity=Decimal("3"), unit=None
    )
    assert item.quantity == Decimal("3")
    assert item.unit is None


def test_items_ordered_by_position(make_list, add_item):
    lst = make_list()
    add_item(lst, text="c", position=2)
    add_item(lst, text="a", position=0)
    add_item(lst, text="b", position=1)
    assert [i.text for i in lst.items.all()] == ["a", "b", "c"]


def test_deleting_recipe_nulls_item_fk(make_list, make_recipe):
    lst = make_list()
    recipe = make_recipe("Doomed")
    item = ListItem.objects.create(list=lst, recipe=recipe, text="Doomed")
    recipe.delete()
    item.refresh_from_db()
    assert item.recipe_id is None
    assert ListItem.objects.filter(pk=item.pk).exists()
    assert item.text == "Doomed"


def test_deleting_recipe_leaves_content_only_item_as_tombstone(make_list, make_recipe):
    """A content-only line (no ``text``) must still survive its recipe's deletion — the
    ``pre_delete`` receiver writes a tombstone ``text`` before the FK is nulled so the
    has-content check constraint still holds (07.1 review, finding 1).
    """
    lst = make_list()
    recipe = make_recipe("Chicken Parm")
    item = ListItem.objects.create(list=lst, recipe=recipe)
    assert item.text == ""

    recipe.delete()

    assert not type(recipe).objects.filter(pk=recipe.pk).exists()
    item.refresh_from_db()
    assert item.recipe_id is None
    assert item.text == "(deleted recipe)"


def test_deleting_dish_leaves_content_only_item_as_tombstone(make_list, make_dish):
    lst = make_list()
    dish = make_dish("Sunday Roast")
    item = ListItem.objects.create(list=lst, dish=dish)

    dish.delete()

    assert not type(dish).objects.filter(pk=dish.pk).exists()
    item.refresh_from_db()
    assert item.dish_id is None
    assert item.text == "(deleted dish)"


def test_deleting_ingredient_leaves_content_only_item_as_tombstone(
    make_list, make_ingredient, gram, alice
):
    lst = make_list()
    ingredient = make_ingredient("Saffron", owner=alice)
    item = ListItem.objects.create(
        list=lst, ingredient=ingredient, quantity=Decimal("2"), unit=gram
    )

    ingredient.delete()

    assert not type(ingredient).objects.filter(pk=ingredient.pk).exists()
    item.refresh_from_db()
    assert item.ingredient_id is None
    assert item.text == "(deleted ingredient)"
    assert item.quantity == Decimal("2")


def test_cascade_delete_still_tombstones(make_list, make_recipe):
    """CO-2: the queryset / fast-delete path still stamps the tombstone. Every other deletion
    test uses ``instance.delete()``; this guards against a silent ``can_fast_delete`` regression
    in a future Django by going through ``Recipe.objects.filter(...).delete()``.
    """
    lst = make_list()
    doomed = make_recipe("Doomed A")
    also_doomed = make_recipe("Doomed B")
    item_a = ListItem.objects.create(list=lst, recipe=doomed)
    item_b = ListItem.objects.create(list=lst, recipe=also_doomed)

    from recipes.models import Recipe

    Recipe.objects.filter(pk__in=[doomed.pk, also_doomed.pk]).delete()

    item_a.refresh_from_db()
    item_b.refresh_from_db()
    assert item_a.recipe_id is None and item_b.recipe_id is None
    assert item_a.text == "(deleted recipe)" and item_b.text == "(deleted recipe)"


def test_deleting_recipe_keeps_existing_text_untouched(make_list, make_recipe):
    """A line with its own content is not overwritten with a tombstone."""
    lst = make_list()
    recipe = make_recipe("Doomed")
    item = ListItem.objects.create(list=lst, recipe=recipe, text="my own note")

    recipe.delete()

    item.refresh_from_db()
    assert item.recipe_id is None
    assert item.text == "my own note"


def test_one_default_shopping_list_per_user(make_list, alice):
    make_list("Shopping List", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_list("Another", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True)


def test_two_users_can_each_have_a_default(make_list, alice, bob):
    a = make_list("A", owner=alice, is_default_shopping_list=True)
    b = make_list("B", owner=bob, is_default_shopping_list=True)
    assert a.is_default_shopping_list and b.is_default_shopping_list


def test_source_defaults_to_manual(make_list):
    lst = make_list()
    item = ListItem.objects.create(list=lst, text="milk")
    assert item.source == ItemSource.MANUAL
