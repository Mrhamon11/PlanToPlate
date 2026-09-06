"""Lists REST API — plain CRUD, the item routes, the actions, filters, pagination
(``Plan/07-Lists-And-Shopping/test-plan.md``, "API"). The IDOR / visibility matrix is in
``test_security.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from lists.models import ItemSource, List, ListItem, ListKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_for(user_factory):
    def _client(**kwargs):
        user = user_factory(**kwargs)
        client = APIClient()
        client.force_login(user)
        return client, user

    return _client


def test_crud_list(client_for):
    client, me = client_for(username="me")

    created = client.post("/api/lists/", {"name": "Groceries", "kind": "SHOPPING"}, format="json")
    assert created.status_code == 201, created.data
    list_id = created.data["id"]
    assert created.data["kind"] == "SHOPPING"
    assert created.data["is_default_shopping_list"] is False

    patched = client.patch(f"/api/lists/{list_id}/", {"name": "Weekly"}, format="json")
    assert patched.status_code == 200
    assert patched.data["name"] == "Weekly"

    assert client.get(f"/api/lists/{list_id}/").status_code == 200
    assert client.delete(f"/api/lists/{list_id}/").status_code == 204
    assert not List.objects.filter(pk=list_id).exists()


def test_is_default_shopping_list_is_read_only(client_for):
    client, me = client_for(username="me")
    created = client.post(
        "/api/lists/",
        {"name": "Sneaky", "kind": "SHOPPING", "is_default_shopping_list": True},
        format="json",
    )
    assert created.status_code == 201
    assert created.data["is_default_shopping_list"] is False


def test_add_item(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me, kind=ListKind.GENERIC)

    response = client.post(f"/api/lists/{lst.pk}/items/", {"text": "Batteries"}, format="json")

    assert response.status_code == 201, response.data
    item = ListItem.objects.get(pk=response.data["id"])
    assert item.list == lst
    assert item.text == "Batteries"
    assert item.source == ItemSource.MANUAL
    assert item.position == 0


def test_add_empty_item_rejected(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me)
    response = client.post(f"/api/lists/{lst.pk}/items/", {}, format="json")
    assert response.status_code == 400


def test_update_item(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me)
    item = ListItem.objects.create(list=lst, text="milk")

    response = client.patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/", {"is_checked": True}, format="json"
    )

    assert response.status_code == 200
    item.refresh_from_db()
    assert item.is_checked is True


def test_delete_item(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me)
    item = ListItem.objects.create(list=lst, text="milk")

    response = client.delete(f"/api/lists/{lst.pk}/items/{item.pk}/")

    assert response.status_code == 204
    assert not ListItem.objects.filter(pk=item.pk).exists()


def test_default_shopping_endpoint_creates(client_for):
    client, me = client_for(username="me")

    response = client.get("/api/lists/default-shopping/")

    assert response.status_code == 200
    assert response.data["is_default_shopping_list"] is True
    assert response.data["kind"] == "SHOPPING"
    assert List.objects.filter(owner=me, is_default_shopping_list=True).count() == 1

    # idempotent
    again = client.get("/api/lists/default-shopping/")
    assert again.data["id"] == response.data["id"]


def test_add_dish_endpoint(client_for, cup):
    client, me = client_for(username="me")
    from meals.models import Dish, DishComponent
    from recipes.models import Recipe, RecipeComponent

    shopping = List.objects.create(name="S", owner=me, kind=ListKind.SHOPPING)
    recipe = Recipe.objects.create(
        name="Curry", instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=me
    )
    from catalog.models import Ingredient

    onion = Ingredient.objects.create(name="Onion", default_unit=cup, is_system=True)
    RecipeComponent.objects.create(recipe=recipe, ingredient=onion, quantity=Decimal("2"), unit=cup)
    dish = Dish.objects.create(name="Curry Night", owner=me)
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"))

    response = client.post(f"/api/lists/{shopping.pk}/add-dish/", {"dish": dish.pk}, format="json")

    assert response.status_code == 201, response.data
    assert {row["ingredient_name"] for row in response.data["items"]} == {"Onion"}
    assert shopping.items.count() == 1


def test_clear_checked_endpoint(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me)
    ListItem.objects.create(list=lst, text="keep", position=0)
    ListItem.objects.create(list=lst, text="gone", position=1, is_checked=True)

    response = client.post(f"/api/lists/{lst.pk}/clear-checked/")

    assert response.status_code == 200
    assert response.data["removed"] == 1
    assert [i.text for i in lst.items.all()] == ["keep"]


def test_merge_duplicates_endpoint(client_for, gram):
    client, me = client_for(username="me")
    from catalog.models import Ingredient

    lst = List.objects.create(name="L", owner=me)
    flour = Ingredient.objects.create(name="Flour", default_unit=gram, is_system=True)
    ListItem.objects.create(list=lst, ingredient=flour, quantity=Decimal("100"), unit=gram)
    ListItem.objects.create(list=lst, ingredient=flour, quantity=Decimal("200"), unit=gram)

    response = client.post(f"/api/lists/{lst.pk}/merge-duplicates/")

    assert response.status_code == 200
    assert response.data["merged"] == 1
    assert lst.items.count() == 1


def test_reorder_endpoint(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="L", owner=me)
    a = ListItem.objects.create(list=lst, text="a", position=0)
    b = ListItem.objects.create(list=lst, text="b", position=1)

    response = client.patch(
        f"/api/lists/{lst.pk}/reorder/", {"item_ids": [b.pk, a.pk]}, format="json"
    )

    assert response.status_code == 200
    assert [i.text for i in lst.items.all()] == ["b", "a"]


def test_filter_by_kind(client_for):
    client, me = client_for(username="me")
    List.objects.create(name="Shop", owner=me, kind=ListKind.SHOPPING)
    List.objects.create(name="Ideas", owner=me, kind=ListKind.GENERIC)

    names = {row["name"] for row in client.get("/api/lists/?kind=SHOPPING").data["results"]}
    assert names == {"Shop"}


def test_item_pagination_over_200(client_for):
    client, me = client_for(username="me")
    lst = List.objects.create(name="Big", owner=me)
    ListItem.objects.bulk_create(
        [ListItem(list=lst, text=f"item {n}", position=n) for n in range(201)]
    )

    detail = client.get(f"/api/lists/{lst.pk}/")
    assert detail.status_code == 200
    assert len(detail.data["items"]) == 200
    assert detail.data["item_count"] == 201
    assert detail.data["items_truncated"] is True

    paged = client.get(f"/api/lists/{lst.pk}/items/")
    assert paged.status_code == 200
    assert paged.data["count"] == 201


# --- 07.23: PATCH quantity / unit shares lists.services.update_item -------------------


def _flour_item(owner, gram):
    from catalog.models import Ingredient

    lst = List.objects.create(name="L", owner=owner, kind=ListKind.SHOPPING)
    flour = Ingredient.objects.create(name="Flour", default_unit=gram, is_system=True)
    item = ListItem.objects.create(
        list=lst,
        ingredient=flour,
        quantity=Decimal("2"),
        unit=gram,
        source=ItemSource.GENERATED,
    )
    return lst, item


def test_patch_item_quantity_and_unit_persists_and_keeps_source(client_for, gram, kilogram):
    client, me = client_for(username="me")
    lst, item = _flour_item(me, gram)

    response = client.patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/",
        {"quantity": "1.5", "unit": kilogram.pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    item.refresh_from_db()
    assert item.quantity == Decimal("1.500")
    assert item.unit == kilogram
    assert item.source == ItemSource.GENERATED


def test_patch_item_unit_without_quantity_rejected(client_for, gram):
    client, me = client_for(username="me")
    lst, item = _flour_item(me, gram)

    response = client.patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/",
        {"quantity": None, "unit": gram.pk},
        format="json",
    )

    assert response.status_code == 400
    item.refresh_from_db()
    assert item.quantity == Decimal("2.000")


@pytest.mark.parametrize("bad_quantity", ["nan", "Infinity", "-Infinity", "-3", "123456789"])
def test_patch_item_rejects_non_finite_negative_or_oversized_quantity(
    client_for, gram, bad_quantity
):
    client, me = client_for(username="me")
    lst, item = _flour_item(me, gram)

    response = client.patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/",
        {"quantity": bad_quantity},
        format="json",
    )

    assert response.status_code == 400, response.data
    item.refresh_from_db()
    assert item.quantity == Decimal("2.000")


def test_patch_item_can_clear_quantity(client_for, gram):
    client, me = client_for(username="me")
    lst, item = _flour_item(me, gram)

    response = client.patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/", {"quantity": None}, format="json"
    )

    assert response.status_code == 200, response.data
    item.refresh_from_db()
    assert item.quantity is None
    assert item.unit is None
