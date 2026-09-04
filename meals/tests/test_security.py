"""Dish / RecipeBook visibility & IDOR matrix (``Plan/06-Dishes-And-RecipeBooks/
test-plan.md``, "Security").

``test_recipe_typeahead_filtered`` now lives in ``test_views.py`` alongside the dish form's
recipe typeahead endpoint it exercises; the API-level equivalent (an invisible recipe ID
cannot be added to a book or dish) is covered here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from meals.models import Dish, DishComponent, DishStats, RecipeBook, RecipeBookEntry
from recipes.models import Recipe, RecipeComponent

pytestmark = pytest.mark.django_db


def _client(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def carol(user_factory):
    return user_factory(username="carol")


def _recipe(owner, cup, name="R", **kw):
    defaults = dict(
        name=name, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=owner
    )
    defaults.update(kw)
    return Recipe.objects.create(**defaults)


# --- IDOR matrix -----------------------------------------------------------------------


def test_dish_idor_matrix(alice, carol, cup):
    private = Dish.objects.create(name="Alice Private", owner=alice, visibility="PRIVATE")
    shared = Dish.objects.create(name="Alice Shared", owner=alice, visibility="SHARED")
    shared.shared_with.add(carol)
    public = Dish.objects.create(name="Alice Public", owner=alice, visibility="PUBLIC")
    mine = Dish.objects.create(name="Carol Own", owner=carol, visibility="PRIVATE")

    carol_client = _client(carol)

    assert carol_client.get(f"/api/dishes/{private.pk}/").status_code == 404
    assert carol_client.get(f"/api/dishes/{shared.pk}/").status_code == 200
    assert carol_client.get(f"/api/dishes/{public.pk}/").status_code == 200

    listed = {row["id"] for row in carol_client.get("/api/dishes/").data["results"]}
    assert listed == {shared.pk, public.pk, mine.pk}

    # shared → readable, not writable
    write = carol_client.patch(f"/api/dishes/{shared.pk}/", {"name": "hijacked"}, format="json")
    assert write.status_code == 403
    # private → write attempts 404, not 403 (enumeration-safe)
    assert (
        carol_client.patch(
            f"/api/dishes/{private.pk}/", {"name": "hijacked"}, format="json"
        ).status_code
        == 404
    )
    private.refresh_from_db()
    assert private.name == "Alice Private"


def test_book_idor_matrix(alice, carol, cup):
    private = RecipeBook.objects.create(name="Alice Private", owner=alice, visibility="PRIVATE")
    shared = RecipeBook.objects.create(name="Alice Shared", owner=alice, visibility="SHARED")
    shared.shared_with.add(carol)
    mine = RecipeBook.objects.create(name="Carol Own", owner=carol, visibility="PRIVATE")

    carol_client = _client(carol)

    assert carol_client.get(f"/api/recipe-books/{private.pk}/").status_code == 404
    assert carol_client.get(f"/api/recipe-books/{shared.pk}/").status_code == 200

    listed = {row["id"] for row in carol_client.get("/api/recipe-books/").data["results"]}
    assert listed == {shared.pk, mine.pk}

    # a read-only holder cannot add recipes to someone else's book
    recipe = _recipe(carol, cup, "Carol Recipe")
    add = carol_client.post(
        f"/api/recipe-books/{shared.pk}/recipes/", {"recipe": recipe.pk}, format="json"
    )
    assert add.status_code in (403, 404)
    assert not RecipeBookEntry.objects.filter(book=shared).exists()


# --- the sneakiest read primitive: adding a guessed recipe ID -------------------------


def test_cannot_add_invisible_recipe_to_dish(alice, carol, cup):
    secret = _recipe(alice, cup, "Alice Secret", visibility="PRIVATE")

    response = _client(carol).post(
        "/api/dishes/",
        {"name": "Probe", "components": [{"recipe": secret.pk, "servings": "1"}]},
        format="json",
    )

    assert response.status_code == 400
    assert not Dish.objects.filter(name="Probe").exists()


def test_cannot_add_invisible_recipe_to_book(alice, carol, cup):
    """Otherwise a guessed recipe ID becomes readable through the requester's own book page."""
    secret = _recipe(alice, cup, "Alice Secret", visibility="PRIVATE")
    book = RecipeBook.objects.create(name="Carol Book", owner=carol)

    response = _client(carol).post(
        f"/api/recipe-books/{book.pk}/recipes/", {"recipe": secret.pk}, format="json"
    )

    assert response.status_code in (400, 404)
    assert not RecipeBookEntry.objects.filter(book=book).exists()


def test_book_detail_does_not_expand_invisible_recipe(alice, carol, cup):
    """Defence in depth: even if an entry for an invisible recipe somehow exists, the book
    detail must not expand it.
    """
    book = RecipeBook.objects.create(name="Carol Book", owner=carol)
    visible = _recipe(carol, cup, "Carol Own")
    invisible = _recipe(alice, cup, "Alice Private", visibility="PRIVATE")
    RecipeBookEntry.objects.create(book=book, recipe=visible)
    RecipeBookEntry.objects.create(book=book, recipe=invisible)

    response = _client(carol).get(f"/api/recipe-books/{book.pk}/")

    assert response.status_code == 200
    names = {
        entry["recipe_detail"]["name"]
        for section in response.data["sections"]
        for entry in section["entries"]
    }
    assert names == {"Carol Own"}
    assert response.data["recipe_count"] == 1


def test_dish_detail_does_not_expand_invisible_recipe(alice, carol, cup):
    """Defence in depth: even if a component for an invisible recipe somehow exists, dish
    detail must not expand it — not its name/pk, and not into ``total_minutes`` / ``roles``
    (``design.md``, "Security notes"; the D31 unshare-a-child path).
    """
    dish = Dish.objects.create(name="Carol Dinner", owner=carol)
    visible = _recipe(carol, cup, "Carol Own", prep_minutes=10, cook_minutes=20, role="PROTEIN")
    invisible = _recipe(
        alice,
        cup,
        "Alice Private",
        visibility="PRIVATE",
        prep_minutes=100,
        cook_minutes=200,
        role="DESSERT",
    )
    DishComponent.objects.create(dish=dish, recipe=visible, servings=Decimal("1"), position=0)
    DishComponent.objects.create(dish=dish, recipe=invisible, servings=Decimal("1"), position=1)

    response = _client(carol).get(f"/api/dishes/{dish.pk}/")

    assert response.status_code == 200
    assert {c["recipe"] for c in response.data["components"]} == {visible.pk}
    assert {c["recipe_name"] for c in response.data["components"]} == {"Carol Own"}
    assert response.data["total_minutes"] == 30
    assert response.data["roles"] == ["PROTEIN"]


def test_dish_flattened_does_not_expand_invisible_recipe(alice, carol, cup, gram, make_ingredient):
    """``GET /flattened/`` must not walk an invisible component recipe's ingredient graph."""
    dish = Dish.objects.create(name="Carol Dinner", owner=carol)
    visible = _recipe(carol, cup, "Carol Own")
    RecipeComponent.objects.create(
        recipe=visible, ingredient=make_ingredient("Tomato"), quantity=Decimal("100"), unit=gram
    )
    invisible = _recipe(alice, cup, "Alice Private", visibility="PRIVATE")
    RecipeComponent.objects.create(
        recipe=invisible,
        ingredient=make_ingredient("Secret Spice"),
        quantity=Decimal("500"),
        unit=gram,
    )
    DishComponent.objects.create(dish=dish, recipe=visible, servings=Decimal("1"))
    DishComponent.objects.create(dish=dish, recipe=invisible, servings=Decimal("1"))

    response = _client(carol).get(f"/api/dishes/{dish.pk}/flattened/")

    assert response.status_code == 200
    assert {row["ingredient"]["name"] for row in response.data} == {"Tomato"}


# --- per-user stats are private ------------------------------------------------------


def test_dish_stats_private(alice, carol, cup):
    dish = Dish.objects.create(name="D", owner=alice, visibility="PUBLIC")
    DishStats.objects.create(user=alice, dish=dish, rating=5, is_favorite=True)

    carol_view = _client(carol).get(f"/api/dishes/{dish.pk}/stats/")
    assert carol_view.status_code == 200
    assert carol_view.data["rating"] is None
    assert carol_view.data["is_favorite"] is False

    _client(carol).put(f"/api/dishes/{dish.pk}/stats/", {"rating": 1}, format="json")
    assert DishStats.objects.get(user=alice, dish=dish).rating == 5
    assert DishStats.objects.get(user=carol, dish=dish).rating == 1


def test_cannot_write_dish_stats_on_invisible_dish(alice, carol, cup):
    dish = Dish.objects.create(name="D", owner=alice, visibility="PRIVATE")
    assert _client(carol).post(f"/api/dishes/{dish.pk}/made/").status_code == 404
