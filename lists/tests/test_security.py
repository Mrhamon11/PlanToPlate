"""Lists visibility & IDOR matrix (``Plan/07-Lists-And-Shopping/test-plan.md``, "Security").

The load-bearing rule: every content FK on an item is validated as visible to the actor on
write, and no count or preview leaks invisible content on read (design.md, "Security notes").
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog.models import Ingredient
from lists.models import List, ListItem, ListKind
from lists.services import ListVisibilityError, populate_shopping_list
from meals.models import Dish, DishComponent
from recipes.models import Recipe, RecipeComponent

pytestmark = pytest.mark.django_db


def _client(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


def _recipe(owner, cup, name="R", **kw):
    defaults = dict(
        name=name, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=owner
    )
    defaults.update(kw)
    return Recipe.objects.create(**defaults)


def test_list_idor_matrix(alice, bob, cup):
    private = List.objects.create(name="Alice Private", owner=alice, visibility="PRIVATE")
    shared = List.objects.create(name="Alice Shared", owner=alice, visibility="SHARED")
    shared.shared_with.add(bob)
    public = List.objects.create(name="Alice Public", owner=alice, visibility="PUBLIC")
    mine = List.objects.create(name="Bob Own", owner=bob, visibility="PRIVATE")

    bob_client = _client(bob)

    assert bob_client.get(f"/api/lists/{private.pk}/").status_code == 404
    assert bob_client.get(f"/api/lists/{shared.pk}/").status_code == 200
    assert bob_client.get(f"/api/lists/{public.pk}/").status_code == 200

    listed = {row["id"] for row in bob_client.get("/api/lists/").data["results"]}
    assert listed == {shared.pk, public.pk, mine.pk}

    # shared → readable, not writable
    assert (
        bob_client.patch(
            f"/api/lists/{shared.pk}/", {"name": "hijacked"}, format="json"
        ).status_code
        == 403
    )
    # private → 404, enumeration-safe
    assert (
        bob_client.patch(
            f"/api/lists/{private.pk}/", {"name": "hijacked"}, format="json"
        ).status_code
        == 404
    )


def test_cannot_add_invisible_recipe_to_list(alice, bob, cup):
    secret = _recipe(alice, cup, "Alice Secret", visibility="PRIVATE")
    lst = List.objects.create(name="Bob List", owner=bob)

    response = _client(bob).post(
        f"/api/lists/{lst.pk}/items/", {"recipe": secret.pk}, format="json"
    )

    assert response.status_code == 400
    assert not lst.items.exists()


def test_cannot_add_invisible_dish_to_list(alice, bob, cup):
    secret = Dish.objects.create(name="Alice Secret Dish", owner=alice, visibility="PRIVATE")
    lst = List.objects.create(name="Bob List", owner=bob)

    response = _client(bob).post(f"/api/lists/{lst.pk}/items/", {"dish": secret.pk}, format="json")

    assert response.status_code == 400
    assert not lst.items.exists()


def test_cannot_add_invisible_ingredient_to_list(alice, bob, gram):
    secret = Ingredient.objects.create(
        name="Alice Private Spice", default_unit=gram, owner=alice, visibility="PRIVATE"
    )
    lst = List.objects.create(name="Bob List", owner=bob)

    response = _client(bob).post(
        f"/api/lists/{lst.pk}/items/",
        {"ingredient": secret.pk, "quantity": "5", "unit": gram.pk},
        format="json",
    )

    assert response.status_code == 400
    assert not lst.items.exists()


def test_cannot_populate_from_invisible_dish(alice, bob, cup, gram):
    dish = Dish.objects.create(name="Alice Secret", owner=alice, visibility="PRIVATE")
    recipe = _recipe(alice, cup, "R")
    RecipeComponent.objects.create(
        recipe=recipe,
        ingredient=Ingredient.objects.create(name="X", default_unit=gram, is_system=True),
        quantity=Decimal("1"),
        unit=gram,
    )
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"))
    bob_list = List.objects.create(name="Bob Shopping", owner=bob, kind=ListKind.SHOPPING)

    with pytest.raises(ListVisibilityError):
        populate_shopping_list(bob_list, [dish])
    assert bob_list.items.count() == 0

    # And through the add-dish endpoint.
    response = _client(bob).post(
        f"/api/lists/{bob_list.pk}/add-dish/", {"dish": dish.pk}, format="json"
    )
    assert response.status_code == 400


def test_shared_list_is_read_only(alice, bob):
    lst = List.objects.create(name="Alice Shopping", owner=alice, visibility="SHARED")
    lst.shared_with.add(bob)
    item = ListItem.objects.create(list=lst, text="milk")

    bob_client = _client(bob)
    # cannot check an item off
    assert (
        bob_client.patch(
            f"/api/lists/{lst.pk}/items/{item.pk}/", {"is_checked": True}, format="json"
        ).status_code
        == 403
    )
    # cannot add
    assert (
        bob_client.post(f"/api/lists/{lst.pk}/items/", {"text": "eggs"}, format="json").status_code
        == 403
    )
    # cannot clear / reorder
    assert bob_client.post(f"/api/lists/{lst.pk}/clear-checked/").status_code == 403
    item.refresh_from_db()
    assert item.is_checked is False


def test_item_rejects_two_content_fks(alice, cup):
    """CO-1: ``POST …/items/ {"recipe": R, "dish": D}`` with no text is rejected —
    ``ListItemSerializer`` enforces exactly one content FK, closing the ``pre_delete`` receiver's
    multi-cascade blind spot.
    """
    recipe = _recipe(alice, cup, "R")
    dish = Dish.objects.create(name="D", owner=alice)
    lst = List.objects.create(name="Alice List", owner=alice)

    response = _client(alice).post(
        f"/api/lists/{lst.pk}/items/",
        {"recipe": recipe.pk, "dish": dish.pk},
        format="json",
    )

    assert response.status_code == 400
    assert not lst.items.exists()


def test_cannot_modify_others_items_directly(alice, bob):
    """Hitting the item endpoint under someone else's private list id → 404, not 403."""
    lst = List.objects.create(name="Alice Private", owner=alice, visibility="PRIVATE")
    item = ListItem.objects.create(list=lst, text="milk")

    response = _client(bob).patch(
        f"/api/lists/{lst.pk}/items/{item.pk}/", {"is_checked": True}, format="json"
    )
    assert response.status_code == 404


def test_list_index_counts_do_not_leak(alice, bob, cup):
    """A shared list whose item points at a recipe the recipient cannot see renders that name
    as null — no preview leak — while the item still counts (the recipient knows a line is
    there, just not what).
    """
    secret = _recipe(alice, cup, "Secret Sauce", visibility="PRIVATE")
    lst = List.objects.create(name="Alice Shared", owner=alice, visibility="SHARED")
    lst.shared_with.add(bob)
    ListItem.objects.create(list=lst, recipe=secret, text="")

    detail = _client(bob).get(f"/api/lists/{lst.pk}/")

    assert detail.status_code == 200
    assert detail.data["items"][0]["recipe_name"] is None
    assert "Secret Sauce" not in str(detail.data)

    # the owner still sees the name
    owner_detail = _client(alice).get(f"/api/lists/{lst.pk}/")
    assert owner_detail.data["items"][0]["recipe_name"] == "Secret Sauce"
