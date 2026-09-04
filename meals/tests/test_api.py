"""Meals API surface (``Plan/06-Dishes-And-RecipeBooks/test-plan.md``, "API").

The IDOR / visibility matrix lives in ``test_security.py``; this covers plain CRUD, the nested
component write, the dish actions, and the book add / remove / reorder / ordering surface.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from meals.models import Dish, DishComponent, DishStats, RecipeBook, RecipeBookEntry
from recipes.models import Recipe, RecipeComponent, RecipeStats

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_for(user_factory):
    def _client(**user_kwargs):
        user = user_factory(**user_kwargs)
        client = APIClient()
        client.force_login(user)
        return client, user

    return _client


def _recipe(owner, cup, name="R", **kw):
    defaults = dict(
        name=name, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=owner
    )
    defaults.update(kw)
    return Recipe.objects.create(**defaults)


# --- dish nested writes --------------------------------------------------------------------


def test_create_dish_with_components(client_for, cup):
    client, me = client_for(username="me")
    r1 = _recipe(me, cup, "Roast")
    r2 = _recipe(me, cup, "Rice")

    response = client.post(
        "/api/dishes/",
        {
            "name": "Sunday Roast",
            "components": [
                {"recipe": r1.pk, "servings": "2"},
                {"recipe": r2.pk, "servings": "1"},
            ],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    dish = Dish.objects.get(pk=response.data["id"])
    assert dish.owner == me
    assert dish.components.count() == 2
    assert [c.position for c in dish.components.all()] == [0, 1]
    assert dish.components.get(recipe=r1).servings == Decimal("2.00")


def test_dish_nested_write_atomic(client_for, cup):
    client, me = client_for(username="me")
    good = _recipe(me, cup, "Good")
    other = _recipe(client_for(username="other")[1], cup, "Secret", visibility="PRIVATE")

    response = client.post(
        "/api/dishes/",
        {
            "name": "Broken",
            "components": [
                {"recipe": good.pk, "servings": "1"},
                {"recipe": other.pk, "servings": "1"},
            ],
        },
        format="json",
    )

    assert response.status_code == 400
    assert Dish.objects.count() == 0
    assert DishComponent.objects.count() == 0


def test_create_dish_without_components(client_for, cup):
    """design.md "Edge cases": an empty dish is allowed to exist while being built — the API
    keeps the same contract as the HTML form (``components`` is optional).
    """
    client, me = client_for(username="me")

    response = client.post("/api/dishes/", {"name": "Blank"}, format="json")

    assert response.status_code == 201, response.data
    dish = Dish.objects.get(pk=response.data["id"])
    assert dish.components.count() == 0


def test_dish_flattened_endpoint(client_for, cup, gram, make_ingredient):
    client, me = client_for(username="me")
    salsa = _recipe(me, cup, "Salsa")
    tomato = make_ingredient("Tomato")
    RecipeComponent.objects.create(
        recipe=salsa, ingredient=tomato, quantity=Decimal("300"), unit=gram
    )
    sauce = _recipe(me, cup, "Sauce")
    RecipeComponent.objects.create(
        recipe=sauce, ingredient=tomato, quantity=Decimal("500"), unit=gram
    )
    dish = Dish.objects.create(name="Taco Night", owner=me)
    DishComponent.objects.create(dish=dish, recipe=salsa, servings=Decimal("2"))
    DishComponent.objects.create(dish=dish, recipe=sauce, servings=Decimal("1"))

    response = client.get(f"/api/dishes/{dish.pk}/flattened/")

    assert response.status_code == 200
    by_name = {row["ingredient"]["name"]: row for row in response.data}
    # salsa 300 g ×2 + sauce 500 g ×1 = 1100 g, aggregated to one line
    assert Decimal(by_name["Tomato"]["quantity"]) == Decimal("1100")


def test_dish_made_increments_stats(client_for, cup):
    client, me = client_for(username="me")
    dish = Dish.objects.create(name="D", owner=me)

    first = client.post(f"/api/dishes/{dish.pk}/made/")
    assert first.status_code == 200
    assert first.data["times_made"] == 1
    assert first.data["last_made_at"] is not None

    second = client.post(f"/api/dishes/{dish.pk}/made/")
    assert second.data["times_made"] == 2
    assert DishStats.objects.get(user=me, dish=dish).times_made == 2


def test_dish_stats_put(client_for, cup):
    client, me = client_for(username="me")
    dish = Dish.objects.create(name="D", owner=me)

    put = client.put(
        f"/api/dishes/{dish.pk}/stats/", {"rating": 4, "is_favorite": True}, format="json"
    )
    assert put.status_code == 200
    assert put.data["rating"] == 4
    assert DishStats.objects.get(user=me, dish=dish).is_favorite is True

    bad = client.put(f"/api/dishes/{dish.pk}/stats/", {"rating": 9}, format="json")
    assert bad.status_code == 400


# --- book add / remove / reorder ----------------------------------------------------------


def test_add_recipe_to_book(client_for, cup):
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="Weeknights", owner=me)
    recipe = _recipe(me, cup, "Pasta")

    response = client.post(
        f"/api/recipe-books/{book.pk}/recipes/",
        {"recipe": recipe.pk, "section": "Quick"},
        format="json",
    )

    assert response.status_code == 201, response.data
    entry = RecipeBookEntry.objects.get(book=book, recipe=recipe)
    assert entry.section == "Quick"


def test_add_duplicate_recipe_returns_400(client_for, cup):
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="B", owner=me)
    recipe = _recipe(me, cup, "Pasta")
    RecipeBookEntry.objects.create(book=book, recipe=recipe)

    response = client.post(
        f"/api/recipe-books/{book.pk}/recipes/", {"recipe": recipe.pk}, format="json"
    )

    assert response.status_code == 400
    assert book.entries.count() == 1


def test_remove_recipe_from_book(client_for, cup):
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="B", owner=me)
    recipe = _recipe(me, cup, "Pasta")
    RecipeBookEntry.objects.create(book=book, recipe=recipe)

    response = client.delete(f"/api/recipe-books/{book.pk}/recipes/{recipe.pk}/")

    assert response.status_code == 204
    assert book.entries.count() == 0

    missing = client.delete(f"/api/recipe-books/{book.pk}/recipes/{recipe.pk}/")
    assert missing.status_code == 404


def test_reorder_book_entries(client_for, cup):
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="B", owner=me)
    a = _recipe(me, cup, "A")
    b = _recipe(me, cup, "B")
    RecipeBookEntry.objects.create(book=book, recipe=a, position=0)
    RecipeBookEntry.objects.create(book=book, recipe=b, position=1)

    response = client.patch(
        f"/api/recipe-books/{book.pk}/reorder/",
        {
            "entries": [
                {"recipe": a.pk, "position": 5, "section": "Later"},
                {"recipe": b.pk, "position": 0},
            ]
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    assert RecipeBookEntry.objects.get(book=book, recipe=a).position == 5
    assert RecipeBookEntry.objects.get(book=book, recipe=a).section == "Later"
    assert RecipeBookEntry.objects.get(book=book, recipe=b).position == 0


def test_reorder_rejects_recipe_not_in_book(client_for, cup):
    """A ``recipe`` id the book does not contain is a 400, not a silent 0-row update + 200."""
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="B", owner=me)
    a = _recipe(me, cup, "A")
    RecipeBookEntry.objects.create(book=book, recipe=a, position=0)
    stranger = _recipe(me, cup, "Not Filed")

    response = client.patch(
        f"/api/recipe-books/{book.pk}/reorder/",
        {"entries": [{"recipe": a.pk, "position": 1}, {"recipe": stranger.pk, "position": 0}]},
        format="json",
    )

    assert response.status_code == 400
    assert RecipeBookEntry.objects.get(book=book, recipe=a).position == 0


def test_book_ordering_by_name(client_for, cup):
    client, me = client_for(username="me")
    book = RecipeBook.objects.create(name="B", owner=me)
    for name in ("Ziti", "Alfredo", "Marinara"):
        RecipeBookEntry.objects.create(book=book, recipe=_recipe(me, cup, name), section="")

    response = client.get(f"/api/recipe-books/{book.pk}/?ordering=name")

    assert response.status_code == 200
    names = [e["recipe_detail"]["name"] for e in response.data["sections"][0]["entries"]]
    assert names == ["Alfredo", "Marinara", "Ziti"]


def test_book_ordering_by_rating_uses_requester_stats(client_for, cup):
    """Bob's ordering reflects Bob's ratings, not Alice's."""
    alice_client, alice = client_for(username="alice")
    bob_client, bob = client_for(username="bob")
    book = RecipeBook.objects.create(name="Shared", owner=alice, visibility="PUBLIC")
    low = _recipe(alice, cup, "Low", visibility="PUBLIC")
    high = _recipe(alice, cup, "High", visibility="PUBLIC")
    RecipeBookEntry.objects.create(book=book, recipe=low)
    RecipeBookEntry.objects.create(book=book, recipe=high)

    RecipeStats.objects.create(user=alice, recipe=low, rating=5)
    RecipeStats.objects.create(user=alice, recipe=high, rating=1)
    RecipeStats.objects.create(user=bob, recipe=low, rating=1)
    RecipeStats.objects.create(user=bob, recipe=high, rating=5)

    bob_names = [
        e["recipe_detail"]["name"]
        for e in bob_client.get(f"/api/recipe-books/{book.pk}/?ordering=rating").data["sections"][
            0
        ]["entries"]
    ]
    assert bob_names == ["High", "Low"]

    alice_names = [
        e["recipe_detail"]["name"]
        for e in alice_client.get(f"/api/recipe-books/{book.pk}/?ordering=rating").data["sections"][
            0
        ]["entries"]
    ]
    assert alice_names == ["Low", "High"]


# --- recipe delete blocked by a dish ----------------------------------------------------


def test_delete_recipe_in_dish_returns_409(client_for, cup):
    client, me = client_for(username="me")
    recipe = _recipe(me, cup, "Taco Filling")
    dish = Dish.objects.create(name="Taco Night", owner=me)
    DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"))

    response = client.delete(f"/api/recipes/{recipe.pk}/")

    assert response.status_code == 409
    assert "Taco Night" in str(response.data)
    assert Recipe.objects.filter(pk=recipe.pk).exists()


def test_delete_recipe_in_dish_does_not_leak_invisible_dish(client_for, cup, user_factory):
    client, me = client_for(username="me")
    recipe = _recipe(me, cup, "Shared Recipe", visibility="PUBLIC")
    stranger = user_factory(username="stranger")
    secret_dish = Dish.objects.create(name="Strangers Secret Dinner", owner=stranger)
    DishComponent.objects.create(dish=secret_dish, recipe=recipe, servings=Decimal("1"))

    response = client.delete(f"/api/recipes/{recipe.pk}/")

    assert response.status_code == 409
    body = str(response.data)
    assert "Strangers Secret Dinner" not in body
    assert "1 other dish" in body


def test_delete_recipe_in_two_dishes_pluralises_clause(client_for, cup):
    client, me = client_for(username="me")
    recipe = _recipe(me, cup, "Taco Filling")
    for name in ("Taco Night", "Taco Tuesday"):
        dish = Dish.objects.create(name=name, owner=me)
        DishComponent.objects.create(dish=dish, recipe=recipe, servings=Decimal("1"))

    response = client.delete(f"/api/recipes/{recipe.pk}/")

    assert response.status_code == 409
    body = str(response.data)
    assert "part of the dishes:" in body
    assert "part of the dish:" not in body


# --- dish filters ---------------------------------------------------------------------


def test_dish_filters(client_for, cup, make_tag):
    client, me = client_for(username="me")
    protein = _recipe(me, cup, "Steak", role="PROTEIN")
    dessert = _recipe(me, cup, "Cake", role="DESSERT")

    steak_dish = Dish.objects.create(name="Steak Dinner", owner=me)
    DishComponent.objects.create(dish=steak_dish, recipe=protein, servings=Decimal("1"))
    cake_dish = Dish.objects.create(name="Cake Party", owner=me)
    DishComponent.objects.create(dish=cake_dish, recipe=dessert, servings=Decimal("1"))
    tag = make_tag("party", kind="FREEFORM")
    cake_dish.tags.add(tag)

    def names(url):
        return {row["name"] for row in client.get(url).data["results"]}

    assert names("/api/dishes/?search=steak") == {"Steak Dinner"}
    assert names("/api/dishes/?role=PROTEIN") == {"Steak Dinner"}
    assert names(f"/api/dishes/?tags={tag.slug}") == {"Cake Party"}

    DishStats.objects.create(user=me, dish=steak_dish, is_favorite=True)
    assert names("/api/dishes/?favorite=true") == {"Steak Dinner"}


def test_dish_list_query_count(client_for, cup, django_assert_max_num_queries):
    """A page of N dishes stays within a bounded query count — the list serializer resolves
    every component recipe's visibility in one query for the whole page, not one ``visible_to``
    per row (round-2 review finding).
    """
    client, me = client_for(username="me")
    for d in range(12):
        dish = Dish.objects.create(name=f"Dish {d}", owner=me)
        for _ in range(2):
            DishComponent.objects.create(
                dish=dish, recipe=_recipe(me, cup, f"R{d}-{_}"), servings=Decimal("1")
            )

    with django_assert_max_num_queries(13):
        response = client.get("/api/dishes/")

    assert response.status_code == 200
    assert len(response.data["results"]) == 12


def test_book_list_query_count(client_for, cup, django_assert_max_num_queries):
    """Same bound for a page of N books (round-2 review finding in
    ``RecipeBookSerializer._visible_entries``).
    """
    client, me = client_for(username="me")
    for b in range(12):
        book = RecipeBook.objects.create(name=f"Book {b}", owner=me)
        for _ in range(2):
            RecipeBookEntry.objects.create(book=book, recipe=_recipe(me, cup, f"R{b}-{_}"))

    with django_assert_max_num_queries(13):
        response = client.get("/api/recipe-books/")

    assert response.status_code == 200
    assert len(response.data["results"]) == 12


def test_meals_routes_appear_in_schema(client_for):
    client, _ = client_for(username="me")
    schema = client.get("/api/schema/").content.decode()
    for path in (
        "/api/dishes/",
        "/api/dishes/{id}/flattened/",
        "/api/dishes/{id}/made/",
        "/api/recipe-books/",
        "/api/recipe-books/{id}/reorder/",
    ):
        assert path in schema, path
