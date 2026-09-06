"""``populate_shopping_list`` — the heart of task 07 (``Plan/07-Lists-And-Shopping/
test-plan.md``, "Population"). C8 lives here: regeneration must not duplicate, must not touch
manual lines, and must be scoped to its own plan.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from lists.models import ItemSource, ListItem, ListKind
from lists.services import ListVisibilityError, populate_shopping_list

pytestmark = pytest.mark.django_db


@pytest.fixture
def shopping_list(make_list, alice):
    return make_list("Shopping List", owner=alice, kind=ListKind.SHOPPING)


@pytest.fixture
def plan(alice):
    from planner.models import MealPlan

    return MealPlan.objects.create(owner=alice, name="This week")


def test_populate_adds_flattened_ingredients(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    onion = make_ingredient("Onion")
    garlic = make_ingredient("Garlic")
    dish = dish_with_ingredients(
        "Curry", {onion: (Decimal("200"), gram), garlic: (Decimal("30"), gram)}, owner=alice
    )

    result = populate_shopping_list(shopping_list, [dish])

    names = {item.ingredient.name for item in shopping_list.items.all()}
    assert names == {"Onion", "Garlic"}
    assert all(item.source == ItemSource.GENERATED for item in shopping_list.items.all())
    assert result.added == 2


def test_populate_aggregates_across_dishes(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    onion = make_ingredient("Onion")
    curry = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)
    soup = dish_with_ingredients("Soup", {onion: (Decimal("150"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [curry, soup])

    onion_items = [i for i in shopping_list.items.all() if i.ingredient.name == "Onion"]
    assert len(onion_items) == 1
    assert onion_items[0].quantity == Decimal("350")


def test_populate_doubles_a_dish_scheduled_twice(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    """A dish scheduled twice in a plan needs twice the groceries — no dish-level dedupe
    (07.1 review, finding 2).
    """
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    result = populate_shopping_list(shopping_list, [dish, dish])

    onion_item = shopping_list.items.get()
    assert onion_item.quantity == Decimal("400")
    assert result.added == 1


def test_populate_excludes_staples_by_default(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    salt = make_ingredient("Salt", is_staple=True)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients(
        "Curry", {onion: (Decimal("200"), gram), salt: (Decimal("5"), gram)}, owner=alice
    )

    result = populate_shopping_list(shopping_list, [dish])

    assert {i.ingredient.name for i in shopping_list.items.all()} == {"Onion"}
    assert result.staples_skipped == 1


def test_populate_includes_staples_when_asked(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    salt = make_ingredient("Salt", is_staple=True)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients(
        "Curry", {onion: (Decimal("200"), gram), salt: (Decimal("5"), gram)}, owner=alice
    )

    result = populate_shopping_list(shopping_list, [dish], exclude_staples=False)

    assert {i.ingredient.name for i in shopping_list.items.all()} == {"Onion", "Salt"}
    assert result.staples_skipped == 0


def test_regeneration_replaces_generated_items(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice, plan
):
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [dish], source_plan=plan)
    first_count = shopping_list.items.count()
    result = populate_shopping_list(shopping_list, [dish], source_plan=plan)

    assert shopping_list.items.count() == first_count
    assert result.replaced == first_count
    assert result.added == first_count


def test_regeneration_preserves_manual_items(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice, plan, add_item
):
    add_item(shopping_list, text="Batteries", source=ItemSource.MANUAL)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [dish], source_plan=plan)
    populate_shopping_list(shopping_list, [dish], source_plan=plan)

    texts = {i.text for i in shopping_list.items.filter(source=ItemSource.MANUAL)}
    assert "Batteries" in texts
    assert shopping_list.items.filter(text="Batteries").count() == 1


def test_regeneration_scoped_to_source_plan(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    from planner.models import MealPlan

    plan_a = MealPlan.objects.create(owner=alice, name="A")
    plan_b = MealPlan.objects.create(owner=alice, name="B")
    onion = make_ingredient("Onion")
    garlic = make_ingredient("Garlic")
    dish_a = dish_with_ingredients("A dish", {onion: (Decimal("200"), gram)}, owner=alice)
    dish_b = dish_with_ingredients("B dish", {garlic: (Decimal("50"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [dish_a], source_plan=plan_a)
    populate_shopping_list(shopping_list, [dish_b], source_plan=plan_b)
    # Regenerating plan A must not touch plan B's garlic line.
    populate_shopping_list(shopping_list, [dish_a], source_plan=plan_a)

    by_plan = {i.ingredient.name: i.generated_from_id for i in shopping_list.items.all()}
    assert by_plan == {"Onion": plan_a.pk, "Garlic": plan_b.pk}


def test_regeneration_loses_checked_state_documented(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice, plan
):
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [dish], source_plan=plan)
    item = shopping_list.items.get()
    item.is_checked = True
    item.save(update_fields=["is_checked"])

    populate_shopping_list(shopping_list, [dish], source_plan=plan)

    # Accepted behaviour: the replaced generated item comes back unchecked.
    assert shopping_list.items.get().is_checked is False


def test_populate_is_atomic(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice, plan, add_item
):
    add_item(shopping_list, text="Batteries", source=ItemSource.MANUAL)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Curry", {onion: (Decimal("200"), gram)}, owner=alice)
    populate_shopping_list(shopping_list, [dish], source_plan=plan)
    before = {(i.text, i.ingredient_id, i.quantity) for i in shopping_list.items.all()}

    with patch.object(ListItem.objects, "bulk_create", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            populate_shopping_list(shopping_list, [dish], source_plan=plan)

    after = {(i.text, i.ingredient_id, i.quantity) for i in shopping_list.items.all()}
    assert after == before


def test_populate_returns_summary(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice, plan
):
    salt = make_ingredient("Salt", is_staple=True)
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients(
        "Curry", {onion: (Decimal("200"), gram), salt: (Decimal("5"), gram)}, owner=alice
    )

    first = populate_shopping_list(shopping_list, [dish], source_plan=plan)
    assert (first.added, first.replaced, first.staples_skipped) == (1, 0, 1)

    second = populate_shopping_list(shopping_list, [dish], source_plan=plan)
    assert (second.added, second.replaced, second.staples_skipped) == (1, 1, 1)


def test_populate_sets_provenance(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    onion = make_ingredient("Onion")
    dish = dish_with_ingredients("Chicken Parm", {onion: (Decimal("200"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [dish])

    item = shopping_list.items.get()
    assert item.dish_id == dish.pk


def test_populate_provenance_null_when_multiple_dishes_contribute(
    shopping_list, dish_with_ingredients, make_ingredient, gram, alice
):
    onion = make_ingredient("Onion")
    a = dish_with_ingredients("A", {onion: (Decimal("100"), gram)}, owner=alice)
    b = dish_with_ingredients("B", {onion: (Decimal("100"), gram)}, owner=alice)

    populate_shopping_list(shopping_list, [a, b])

    item = shopping_list.items.get()
    assert item.dish_id is None


def test_populate_requires_visibility(
    shopping_list, dish_with_ingredients, make_ingredient, gram, bob
):
    onion = make_ingredient("Onion")
    stranger_dish = dish_with_ingredients("Secret", {onion: (Decimal("200"), gram)}, owner=bob)
    stranger_dish.visibility = "PRIVATE"
    stranger_dish.save(update_fields=["visibility"])

    with pytest.raises(ListVisibilityError):
        populate_shopping_list(shopping_list, [stranger_dish])

    assert shopping_list.items.count() == 0


def test_populate_query_count(
    shopping_list,
    dish_with_ingredients,
    make_ingredient,
    gram,
    alice,
    plan,
    django_assert_max_num_queries,
):
    dishes = []
    for d in range(7):
        ing = make_ingredient(f"Ingredient {d}")
        dishes.append(
            dish_with_ingredients(f"Dish {d}", {ing: (Decimal("100"), gram)}, owner=alice)
        )

    with django_assert_max_num_queries(12):
        populate_shopping_list(shopping_list, dishes, source_plan=plan)

    assert shopping_list.items.count() == 7
