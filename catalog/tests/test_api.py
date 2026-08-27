"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "API".

The IDOR matrix for ``Ingredient`` lives in ``test_security.py`` alongside the other
visibility-bypass tests; this file covers the plain API surface and the two catalog-specific
endpoints (staff-gated unit/tag writes, and ``POST /api/units/convert/``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Ingredient, Unit
from core.models import Visibility

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_for(user_factory):
    def _client(**user_kwargs) -> tuple[APIClient, object]:
        user = user_factory(**user_kwargs)
        client = APIClient()
        client.force_login(user)
        return client, user

    return _client


# --- units / tags --------------------------------------------------------------------------


def test_list_units(client_for, make_unit):
    make_unit("gram")
    make_unit("cup")
    client, _ = client_for()

    response = client.get("/api/units/")

    assert response.status_code == 200
    names = {row["name"] for row in response.data}
    assert {"gram", "cup"} <= names


def test_list_units_filterable_by_dimension(client_for, make_unit):
    make_unit("gram")
    make_unit("cup")
    client, _ = client_for()

    response = client.get("/api/units/?dimension=MASS")

    assert response.status_code == 200
    assert {row["name"] for row in response.data} == {"gram"}


def test_units_readonly_for_regular_user(client_for):
    client, _ = client_for()

    response = client.post(
        "/api/units/",
        {"name": "furlong", "abbrev": "fur", "dimension": "MASS", "to_base_factor": "201168"},
    )

    assert response.status_code == 403
    assert not Unit.objects.filter(name="furlong").exists()


def test_units_writable_by_staff(client_for):
    client, _ = client_for(is_staff=True)

    response = client.post(
        "/api/units/",
        {"name": "stone", "abbrev": "st", "dimension": "MASS", "to_base_factor": "6350.29318"},
    )

    assert response.status_code == 201
    assert Unit.objects.get(name="stone").dimension == "MASS"


def test_tags_readonly_for_regular_user(client_for):
    client, _ = client_for()

    response = client.post("/api/tags/", {"name": "brunch", "kind": "FREEFORM"})

    assert response.status_code == 403


# --- ingredients ---------------------------------------------------------------------------


def test_ingredient_list_respects_visibility(client_for, make_ingredient, user_factory):
    alice = user_factory(username="alice")
    make_ingredient(name="Alice Secret", owner=alice, visibility=Visibility.PRIVATE)
    client, _ = client_for(username="carol")

    response = client.get("/api/ingredients/")

    assert response.status_code == 200
    names = {row["name"] for row in response.data["results"]}
    assert "Alice Secret" not in names


def test_ingredient_create_sets_owner(client_for, make_ingredient, gram, user_factory):
    other = user_factory(username="mallory")
    client, me = client_for(username="me")

    response = client.post(
        "/api/ingredients/",
        {"name": "My Paprika", "default_unit": gram.pk, "owner": other.pk, "is_system": True},
    )

    assert response.status_code == 201
    created = Ingredient.objects.get(name="My Paprika")
    assert created.owner == me
    assert created.is_system is False
    assert created.visibility == Visibility.PRIVATE


def test_ingredient_search(client_for, make_ingredient, user_factory):
    alice = user_factory(username="alice")
    make_ingredient(name="Chicken Breast", owner=alice, visibility=Visibility.PUBLIC)
    make_ingredient(name="Beef Mince", owner=alice, visibility=Visibility.PUBLIC)
    client, _ = client_for(username="carol")

    response = client.get("/api/ingredients/?search=chick")

    assert response.status_code == 200
    assert {row["name"] for row in response.data["results"]} == {"Chicken Breast"}


def test_ingredient_filter_by_tag(client_for, make_ingredient, make_tag, user_factory):
    alice = user_factory(username="alice")
    chicken = make_tag("chicken", kind="PROTEIN")
    tagged = make_ingredient(name="Chicken Thigh", owner=alice, visibility=Visibility.PUBLIC)
    tagged.tags.add(chicken)
    make_ingredient(name="Carrot", owner=alice, visibility=Visibility.PUBLIC)
    client, _ = client_for(username="carol")

    response = client.get(f"/api/ingredients/?tags={chicken.slug}")

    assert response.status_code == 200
    assert {row["name"] for row in response.data["results"]} == {"Chicken Thigh"}


def test_ingredient_filter_mine_excludes_system_and_shared(
    client_for, make_ingredient, user_factory
):
    client, me = client_for(username="me")
    alice = user_factory(username="alice")

    mine = make_ingredient(name="My Salt", owner=me, visibility=Visibility.PRIVATE)
    make_ingredient(name="System Salt")  # is_system row
    shared = make_ingredient(name="Alice Salt", owner=alice, visibility=Visibility.SHARED)
    shared.shared_with.add(me)

    response = client.get("/api/ingredients/?mine=true")

    assert response.status_code == 200
    assert {row["name"] for row in response.data["results"]} == {"My Salt"}
    assert {row["id"] for row in response.data["results"]} == {mine.pk}


# --- conversion endpoint -----------------------------------------------------------------


def test_convert_endpoint_success(client_for, make_unit):
    kilogram = make_unit("kilogram")
    gram = make_unit("gram")
    client, _ = client_for()

    response = client.post(
        "/api/units/convert/",
        {"quantity": "2", "from_unit": kilogram.pk, "to_unit": gram.pk},
    )

    assert response.status_code == 200
    assert Decimal(str(response.data["quantity"])) == Decimal("2000")
    assert response.data["unit"] == "g"


def test_convert_endpoint_incompatible_returns_400(client_for, make_unit):
    gram = make_unit("gram")
    milliliter = make_unit("millilitre")
    client, _ = client_for()

    response = client.post(
        "/api/units/convert/",
        {"quantity": "100", "from_unit": gram.pk, "to_unit": milliliter.pk},
    )

    assert response.status_code == 400
    body = str(response.data).lower()
    assert "gram" in body and "millilitre" in body
    assert "density" in body


def test_convert_endpoint_unbounded_quantity_is_400_not_500(client_for, make_unit):
    """04.1-04.5 review, finding #4: an oversized quantity is caught by the serializer's
    bounded DecimalField, never a ``decimal.InvalidOperation`` 500 in the service.
    """
    kilogram = make_unit("kilogram")
    gram = make_unit("gram")
    client, _ = client_for()

    response = client.post(
        "/api/units/convert/",
        {"quantity": "9" * 60, "from_unit": kilogram.pk, "to_unit": gram.pk},
    )

    assert response.status_code == 400


def test_convert_endpoint_ingredient_must_be_visible(
    client_for, make_unit, make_ingredient, user_factory
):
    """The ``ingredient`` field is scoped to ``visible_to`` — a private row belonging to
    someone else cannot be referenced to probe its density.
    """
    alice = user_factory(username="alice")
    gram = make_unit("gram")
    milliliter = make_unit("millilitre")
    secret = make_ingredient(
        name="Alice Cream", owner=alice, visibility=Visibility.PRIVATE, density_g_per_ml="1.02"
    )
    client, _ = client_for(username="carol")

    response = client.post(
        "/api/units/convert/",
        {
            "quantity": "100",
            "from_unit": gram.pk,
            "to_unit": milliliter.pk,
            "ingredient": secret.pk,
        },
    )

    assert response.status_code == 400
    assert "ingredient" in str(response.data).lower()


# --- copy --------------------------------------------------------------------------------


def test_copy_system_ingredient(client_for, make_ingredient):
    system = make_ingredient(name="Sea Salt", is_staple=True)
    client, me = client_for(username="me")

    response = client.post(f"/api/ingredients/{system.pk}/copy/")

    assert response.status_code == 201
    copy = Ingredient.objects.get(pk=response.data["id"])
    assert copy.owner == me
    assert copy.is_system is False
    assert copy.visibility == Visibility.PRIVATE
    assert copy.copied_from_id == system.pk
    assert copy.is_staple is True


# --- protected delete: synthetic (real end-to-end deferred to task 05) ------------------
# recipes/models.py is still empty, so nothing PROTECTs Ingredient yet. test-plan's
# `test_delete_in_use_returns_409` end-to-end (a real RecipeComponent blocking the delete)
# is DEFERRED to task 05. Until then the handler is proven two ways: a unit test on
# core.exceptions.conflict_from_protected_error (test_exceptions.py), and this test, which
# forces Ingredient.delete() to raise a synthetic ProtectedError and asserts the viewset's
# perform_destroy turns it into a 409 naming the blocker.


def test_delete_raising_protected_error_becomes_409(client_for, make_ingredient, monkeypatch):
    client, me = client_for(username="me")
    ingredient = make_ingredient(name="Doomed", owner=me, visibility=Visibility.PRIVATE)
    blocker = make_ingredient(name="Carbonara Component", owner=me, visibility=Visibility.PRIVATE)

    from django.db.models import ProtectedError

    def boom(self, *args, **kwargs):
        raise ProtectedError("in use", {blocker})

    monkeypatch.setattr("catalog.models.Ingredient.delete", boom)

    response = client.delete(f"/api/ingredients/{ingredient.pk}/")

    assert response.status_code == 409
    assert "Carbonara Component" in str(response.data)
    assert Ingredient.objects.filter(pk=ingredient.pk).exists()


# --- schema / docs ---------------------------------------------------------------------


def test_all_catalog_routes_appear_in_schema(client_for):
    client, _ = client_for()

    schema = client.get(reverse("schema")).content.decode()

    for path in ("/api/units/", "/api/units/convert/", "/api/tags/", "/api/ingredients/"):
        assert path in schema, path
    assert "/api/ingredients/{id}/copy/" in schema
    assert "/api/ingredients/{id}/share/" in schema
