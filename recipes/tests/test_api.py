"""Recipe API surface (``Plan/05-Recipes/test-plan.md``, "API").

The IDOR / visibility-bypass matrix lives in ``test_security.py``; this file covers the plain
CRUD surface, the nested-component write, and the ``scaled`` / ``flattened`` / ``made`` /
``stats`` actions and the list filters.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

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


def _recipe_payload(*, name="Test Recipe", yield_unit, components=None):
    payload = {
        "name": name,
        "instructions": "Mix and cook.",
        "yield_quantity": "4.000",
        "yield_unit": yield_unit.pk,
        "role": "OTHER",
    }
    if components is not None:
        payload["components"] = components
    return payload


# --- nested component writes -------------------------------------------------------------


def test_create_recipe_with_components(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    tomato = make_ingredient("Tomato", owner=me)
    onion = make_ingredient("Onion", owner=me)

    payload = _recipe_payload(
        yield_unit=cup,
        components=[
            {"ingredient": tomato.pk, "quantity": "800", "unit": gram.pk},
            {"ingredient": onion.pk, "quantity": "150", "unit": gram.pk, "note": "diced"},
        ],
    )
    response = client.post("/api/recipes/", payload, format="json")

    assert response.status_code == 201, response.data
    recipe = Recipe.objects.get(pk=response.data["id"])
    assert recipe.owner == me
    assert recipe.components.count() == 2
    assert [c.position for c in recipe.components.all()] == [0, 1]
    assert recipe.components.get(ingredient=onion).note == "diced"


def test_nested_write_is_atomic(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    tomato = make_ingredient("Tomato", owner=me)

    payload = _recipe_payload(
        yield_unit=cup,
        components=[
            {"ingredient": tomato.pk, "quantity": "800", "unit": gram.pk},
            # invalid: references neither an ingredient nor a sub-recipe
            {"quantity": "1", "unit": gram.pk},
        ],
    )
    response = client.post("/api/recipes/", payload, format="json")

    assert response.status_code == 400
    assert Recipe.objects.count() == 0
    assert RecipeComponent.objects.count() == 0


def test_subrecipe_component_with_incompatible_unit_rejected_at_validation(
    client_for, make_unit, cup, gram
):
    """A sub-recipe component whose unit is a different dimension from the sub-recipe's yield
    unit is refused by ``POST`` (design.md, "Edge cases": "refuse at validation with a clear
    message") — not accepted and only failing later as a 400 from ``flattened``.

    NB: this edge is not enumerated in ``test-plan.md``; added with the task 05 review fix.
    """
    client, me = client_for(username="me")
    stock = Recipe.objects.create(
        name="Stock", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    payload = _recipe_payload(
        name="Soup",
        yield_unit=cup,
        # Stock yields in cups (VOLUME); asking for 200 g (MASS) of it is uncomputable.
        components=[{"sub_recipe": stock.pk, "quantity": "200", "unit": gram.pk}],
    )
    response = client.post("/api/recipes/", payload, format="json")

    assert response.status_code == 400, response.data
    body = str(response.data)
    assert "Stock" in body
    assert "gram" in body and "cup" in body
    assert not Recipe.objects.filter(name="Soup").exists()


def test_subrecipe_component_with_compatible_unit_accepted(client_for, make_unit, cup):
    """The same shape, but the component's unit converts into the sub-recipe's yield dimension:
    accepted (240 ml of a recipe yielding in cups)."""
    client, me = client_for(username="me")
    millilitre = make_unit("millilitre")
    stock = Recipe.objects.create(
        name="Stock", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    payload = _recipe_payload(
        name="Soup",
        yield_unit=cup,
        components=[{"sub_recipe": stock.pk, "quantity": "240", "unit": millilitre.pk}],
    )
    response = client.post("/api/recipes/", payload, format="json")

    assert response.status_code == 201, response.data


def test_update_replaces_component_set(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    a = make_ingredient("A", owner=me)
    b = make_ingredient("B", owner=me)
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(recipe=recipe, ingredient=a, quantity=Decimal("1"), unit=gram)

    response = client.patch(
        f"/api/recipes/{recipe.pk}/",
        {"components": [{"ingredient": b.pk, "quantity": "2", "unit": gram.pk}]},
        format="json",
    )

    assert response.status_code == 200, response.data
    components = list(recipe.components.all())
    assert len(components) == 1
    assert components[0].ingredient == b
    assert components[0].quantity == Decimal("2.000")


def test_patch_without_components_key_leaves_them_untouched(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    a = make_ingredient("A", owner=me)
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(recipe=recipe, ingredient=a, quantity=Decimal("1"), unit=gram)

    response = client.patch(f"/api/recipes/{recipe.pk}/", {"name": "Renamed"}, format="json")

    assert response.status_code == 200
    assert recipe.components.count() == 1


# --- actions ----------------------------------------------------------------------------


def test_scaled_endpoint(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("A", owner=me), quantity=Decimal("100"), unit=gram
    )

    response = client.get(f"/api/recipes/{recipe.pk}/scaled/?factor=2")

    assert response.status_code == 200
    assert Decimal(response.data[0]["quantity"]) == Decimal("200")
    recipe.refresh_from_db()
    assert recipe.components.get().quantity == Decimal("100.000")  # nothing persisted


def test_scaled_endpoint_rejects_bad_factor(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    assert client.get(f"/api/recipes/{recipe.pk}/scaled/?factor=abc").status_code == 400
    assert client.get(f"/api/recipes/{recipe.pk}/scaled/?factor=0").status_code == 400


# A malformed ``?factor`` must be a clean 400, never a 500: ``NaN`` / ``sNaN`` make the
# ``<= 0`` comparison raise ``decimal.InvalidOperation``, ``Infinity`` produces nonsense
# ``Infinity`` quantities (and blows up ``flatten``'s quantize), and an oversized exponent
# overflows the scaling multiplication (review finding, blocking).
_MALFORMED_FACTORS = ["NaN", "sNaN", "Infinity", "-Infinity", "1E999999999"]


@pytest.mark.parametrize("bad", _MALFORMED_FACTORS)
def test_scaled_endpoint_rejects_non_finite_factor(client_for, make_ingredient, gram, cup, bad):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("A", owner=me), quantity=Decimal("100"), unit=gram
    )

    response = client.get(f"/api/recipes/{recipe.pk}/scaled/?factor={bad}")

    assert response.status_code == 400, response.data
    assert "factor" in str(response.data).lower()


@pytest.mark.parametrize("bad", _MALFORMED_FACTORS)
def test_flattened_endpoint_rejects_non_finite_factor(client_for, make_ingredient, gram, cup, bad):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=make_ingredient("A", owner=me), quantity=Decimal("100"), unit=gram
    )

    response = client.get(f"/api/recipes/{recipe.pk}/flattened/?factor={bad}")

    assert response.status_code == 400, response.data
    assert "factor" in str(response.data).lower()


def test_flattened_endpoint(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="Salsa", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=recipe,
        ingredient=make_ingredient("Tomato", owner=me),
        quantity=Decimal("800"),
        unit=gram,
    )
    RecipeComponent.objects.create(
        recipe=recipe,
        ingredient=make_ingredient("Salt", owner=me, is_staple=True),
        quantity=Decimal("5"),
        unit=gram,
    )

    response = client.get(f"/api/recipes/{recipe.pk}/flattened/")
    assert response.status_code == 200
    by_name = {row["ingredient"]["name"]: row for row in response.data}
    assert Decimal(by_name["Tomato"]["quantity"]) == Decimal("800")
    assert by_name["Tomato"]["from_recipes"] == ["Salsa"]

    excluded = client.get(f"/api/recipes/{recipe.pk}/flattened/?exclude_staples=true")
    assert {row["ingredient"]["name"] for row in excluded.data} == {"Tomato"}


def test_flattened_endpoint_sub_recipe_scaled_by_yield(client_for, make_ingredient, gram, cup):
    """Marinara yields 4 cups; a parent using 1 cup gets a quarter of its ingredients."""
    client, me = client_for(username="me")
    marinara = Recipe.objects.create(
        name="Marinara", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=marinara,
        ingredient=make_ingredient("Crushed Tomatoes", owner=me),
        quantity=Decimal("800"),
        unit=gram,
    )
    parm = Recipe.objects.create(
        name="Chicken Parm", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=parm, sub_recipe=marinara, quantity=Decimal("1"), unit=cup
    )

    response = client.get(f"/api/recipes/{parm.pk}/flattened/")

    assert response.status_code == 200
    line = next(r for r in response.data if r["ingredient"]["name"] == "Crushed Tomatoes")
    assert Decimal(line["quantity"]) == Decimal("200")


def test_made_endpoint_increments(client_for, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    first = client.post(f"/api/recipes/{recipe.pk}/made/")
    assert first.status_code == 200
    assert first.data["times_made"] == 1
    assert first.data["last_made_at"] is not None

    second = client.post(f"/api/recipes/{recipe.pk}/made/")
    assert second.data["times_made"] == 2


def test_stats_get_and_put(client_for, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    assert client.get(f"/api/recipes/{recipe.pk}/stats/").data["rating"] is None

    put = client.put(
        f"/api/recipes/{recipe.pk}/stats/", {"rating": 4, "is_favorite": True}, format="json"
    )
    assert put.status_code == 200
    assert put.data["rating"] == 4
    assert put.data["is_favorite"] is True
    stats = RecipeStats.objects.get(user=me, recipe=recipe)
    assert stats.rating == 4 and stats.is_favorite is True


@pytest.mark.parametrize("bad", [0, 6])
def test_stats_put_rejects_out_of_range_rating(client_for, cup, bad):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="R", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    response = client.put(f"/api/recipes/{recipe.pk}/stats/", {"rating": bad}, format="json")

    assert response.status_code == 400
    assert not RecipeStats.objects.filter(user=me, recipe=recipe).exists()


# --- filters ---------------------------------------------------------------------------


@pytest.fixture
def _filter_world(client_for, make_ingredient, make_tag, cup, gram):
    client, me = client_for(username="me")

    def _mk(name, **kw):
        defaults = dict(owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup)
        defaults.update(kw)
        return Recipe.objects.create(name=name, **defaults)

    quick = _mk("Quick", role="PROTEIN", prep_minutes=5, cook_minutes=10)
    slow = _mk("Slow", role="DESSERT", prep_minutes=30, cook_minutes=90)
    chicken_tag = make_tag("chicken", kind="PROTEIN")
    quick.tags.add(chicken_tag)

    return client, me, quick, slow, chicken_tag


def _names(response):
    return {row["name"] for row in response.data["results"]}


def test_filter_by_role(_filter_world):
    client, _me, quick, _slow, _tag = _filter_world
    assert _names(client.get("/api/recipes/?role=PROTEIN")) == {"Quick"}


def test_filter_by_tag(_filter_world):
    client, _me, _quick, _slow, tag = _filter_world
    assert _names(client.get(f"/api/recipes/?tags={tag.slug}")) == {"Quick"}


def test_filter_by_max_minutes(_filter_world):
    client, _me, _quick, _slow, _tag = _filter_world
    assert _names(client.get("/api/recipes/?max_minutes=20")) == {"Quick"}


def test_filter_by_min_rating_and_favorite(_filter_world):
    client, me, quick, slow, _tag = _filter_world
    RecipeStats.objects.create(user=me, recipe=quick, rating=5, is_favorite=True)
    RecipeStats.objects.create(user=me, recipe=slow, rating=2, is_favorite=False)

    assert _names(client.get("/api/recipes/?min_rating=4")) == {"Quick"}
    assert _names(client.get("/api/recipes/?favorite=true")) == {"Quick"}


def test_filter_by_rating_uses_requesters_stats(client_for, cup):
    """Bob's ``min_rating`` reads Bob's ratings, not Alice's."""
    alice_client, alice = client_for(username="alice")
    bob_client, bob = client_for(username="bob")
    recipe = Recipe.objects.create(
        name="Shared",
        owner=alice,
        instructions="x",
        yield_quantity=Decimal("4"),
        yield_unit=cup,
        visibility="PUBLIC",
    )
    RecipeStats.objects.create(user=alice, recipe=recipe, rating=5)
    RecipeStats.objects.create(user=bob, recipe=recipe, rating=1)

    assert _names(bob_client.get("/api/recipes/?min_rating=4")) == set()
    assert _names(alice_client.get("/api/recipes/?min_rating=4")) == {"Shared"}


# --- protected delete (05.9) ---------------------------------------------------------


def test_delete_subrecipe_in_use_returns_409(client_for, cup):
    client, me = client_for(username="me")
    marinara = Recipe.objects.create(
        name="Marinara", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    parm = Recipe.objects.create(
        name="Chicken Parm", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=parm, sub_recipe=marinara, quantity=Decimal("1"), unit=cup
    )

    response = client.delete(f"/api/recipes/{marinara.pk}/")

    assert response.status_code == 409
    assert "Chicken Parm" in str(response.data)
    assert Recipe.objects.filter(pk=marinara.pk).exists()


def test_delete_conflict_does_not_leak_invisible_parent_name(client_for, cup, user_factory):
    """The 409 body must not name a parent recipe the requester cannot see — only count it
    (task 05 review, name leak)."""
    client, me = client_for(username="me")
    marinara = Recipe.objects.create(
        name="Marinara",
        owner=me,
        instructions="x",
        yield_quantity=Decimal("4"),
        yield_unit=cup,
        visibility="SHARED",
    )
    bob = user_factory(username="bob")
    marinara.shared_with.add(bob)
    secret = Recipe.objects.create(
        name="Bobs Secret Sauce",
        owner=bob,
        instructions="x",
        yield_quantity=Decimal("4"),
        yield_unit=cup,
    )
    RecipeComponent.objects.create(
        recipe=secret, sub_recipe=marinara, quantity=Decimal("1"), unit=cup
    )

    response = client.delete(f"/api/recipes/{marinara.pk}/")

    assert response.status_code == 409
    body = str(response.data)
    assert "Bobs Secret Sauce" not in body
    assert "1 other recipe" in body
    assert Recipe.objects.filter(pk=marinara.pk).exists()


def test_delete_unused_recipe_succeeds(client_for, cup):
    client, me = client_for(username="me")
    recipe = Recipe.objects.create(
        name="Solo", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )

    assert client.delete(f"/api/recipes/{recipe.pk}/").status_code == 204
    assert not Recipe.objects.filter(pk=recipe.pk).exists()


# --- copy ----------------------------------------------------------------------------


def test_copy_deep_copies_subrecipes(client_for, make_ingredient, gram, cup):
    client, me = client_for(username="me")
    marinara = Recipe.objects.create(
        name="Marinara", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    # System ingredient: the deep copy passes it through by reference (shared vocabulary),
    # so this test isolates the sub-recipe copy, not ingredient duplication.
    RecipeComponent.objects.create(
        recipe=marinara,
        ingredient=make_ingredient("Tomatoes"),
        quantity=Decimal("800"),
        unit=gram,
    )
    parm = Recipe.objects.create(
        name="Parm", owner=me, instructions="x", yield_quantity=Decimal("4"), yield_unit=cup
    )
    RecipeComponent.objects.create(
        recipe=parm, sub_recipe=marinara, quantity=Decimal("1"), unit=cup
    )

    response = client.post(f"/api/recipes/{parm.pk}/copy/")

    assert response.status_code == 201
    copy = Recipe.objects.get(pk=response.data["id"])
    assert copy.copied_from_id == parm.pk
    copied_sub = copy.components.get().sub_recipe
    assert copied_sub.pk != marinara.pk
    assert copied_sub.owner == me


# --- schema ------------------------------------------------------------------------


def test_recipe_routes_appear_in_schema(client_for):
    client, _ = client_for(username="me")
    schema = client.get("/api/schema/").content.decode()
    for path in (
        "/api/recipes/",
        "/api/recipes/{id}/scaled/",
        "/api/recipes/{id}/flattened/",
        "/api/recipes/{id}/made/",
        "/api/recipes/{id}/stats/",
        "/api/recipes/{id}/copy/",
        "/api/recipes/{id}/share/",
    ):
        assert path in schema, path
