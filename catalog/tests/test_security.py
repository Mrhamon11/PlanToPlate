"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Security".

The task 03 IDOR matrix applied to the concrete ``Ingredient`` model (``core/README.md`` §7:
the dummy-fixture suite proves the machinery; this proves ``Ingredient`` is wired to it), plus
the search-specific visibility-bypass and SQL-wildcard checks.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from core.models import Visibility

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


# --- IDOR matrix -------------------------------------------------------------------------


def test_unrelated_user_gets_404_not_403_on_retrieve(alice, carol, make_ingredient):
    obj = make_ingredient(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    response = _client(carol).get(f"/api/ingredients/{obj.pk}/")

    assert response.status_code == 404


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_unrelated_user_cannot_write_others_ingredient(alice, carol, make_ingredient, method):
    obj = make_ingredient(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)

    response = getattr(_client(carol), method)(f"/api/ingredients/{obj.pk}/", {"name": "hijacked"})

    assert response.status_code == 404
    obj.refresh_from_db()
    assert obj.name == "Alice Private"


def test_list_excludes_others_private(alice, carol, make_ingredient):
    make_ingredient(name="Alice Private", owner=alice, visibility=Visibility.PRIVATE)
    mine = make_ingredient(name="Carol Own", owner=carol, visibility=Visibility.PRIVATE)

    response = _client(carol).get("/api/ingredients/")

    ids = {row["id"] for row in response.data["results"]}
    assert ids == {mine.pk}


def test_shared_ingredient_is_readable_but_not_writable(alice, carol, make_ingredient):
    obj = make_ingredient(name="Alice Shared", owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(carol)
    client = _client(carol)

    assert client.get(f"/api/ingredients/{obj.pk}/").status_code == 200

    write = client.patch(f"/api/ingredients/{obj.pk}/", {"name": "changed"})
    assert write.status_code == 403
    obj.refresh_from_db()
    assert obj.name == "Alice Shared"


def test_cannot_modify_system_ingredient_even_as_staff(user_factory, make_ingredient):
    staff = user_factory(username="staff", is_staff=True, is_superuser=True)
    system = make_ingredient(name="System Nutmeg")

    response = _client(staff).patch(f"/api/ingredients/{system.pk}/", {"is_staple": True})

    assert response.status_code == 403
    system.refresh_from_db()
    assert system.is_staple is False


def test_cannot_share_others_ingredient(alice, carol, make_ingredient):
    obj = make_ingredient(name="Alice Shared", owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(carol)

    response = _client(carol).post(f"/api/ingredients/{obj.pk}/share/", {"users": [carol.pk]})

    assert response.status_code == 403


def test_cannot_read_shares_audience_of_others_ingredient(alice, carol, make_ingredient):
    obj = make_ingredient(name="Alice Shared", owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(carol)

    response = _client(carol).get(f"/api/ingredients/{obj.pk}/shares/")

    assert response.status_code == 403


def test_shared_with_field_is_owner_only_on_retrieve(alice, carol, user_factory, make_ingredient):
    """The plain retrieve endpoint must not become a second, ungated path to the audience the
    owner-only ``/shares/`` action protects (``ARCHITECTURE.md`` D35). A read-only holder — and
    any viewer of a PUBLIC row — sees ``shared_with: []``; the owner sees the real list.
    """
    dan = user_factory(username="dan")
    obj = make_ingredient(name="Alice Shared", owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(carol, dan)

    holder = _client(carol).get(f"/api/ingredients/{obj.pk}/")
    assert holder.status_code == 200
    assert holder.data["shared_with"] == []

    owner = _client(alice).get(f"/api/ingredients/{obj.pk}/")
    assert owner.status_code == 200
    assert set(owner.data["shared_with"]) == {carol.pk, dan.pk}


def test_shared_with_field_empty_for_public_viewer(alice, carol, make_ingredient):
    obj = make_ingredient(name="Alice Public", owner=alice, visibility=Visibility.PUBLIC)
    obj.shared_with.add(carol)

    response = _client(carol).get(f"/api/ingredients/{obj.pk}/")

    assert response.status_code == 200
    assert response.data["shared_with"] == []


# --- search must compose with visible_to, never replace it -----------------------------


def test_search_does_not_leak_invisible_rows(alice, carol, make_ingredient):
    """Searching the *exact* private name still returns nothing — the search filter narrows
    ``visible_to(carol)``, it does not run against every row (test-plan: "Search is a classic
    visibility bypass").
    """
    make_ingredient(name="Alice Truffle Oil", owner=alice, visibility=Visibility.PRIVATE)

    response = _client(carol).get("/api/ingredients/?search=Alice Truffle Oil")

    assert response.status_code == 200
    assert response.data["results"] == []


def test_sql_wildcards_in_search_are_literal(alice, make_ingredient):
    make_ingredient(name="100% Juice", owner=alice, visibility=Visibility.PUBLIC)
    make_ingredient(name="100X Juice", owner=alice, visibility=Visibility.PUBLIC)
    make_ingredient(name="Apple_Pie Spice", owner=alice, visibility=Visibility.PUBLIC)
    make_ingredient(name="AppleXPie Spice", owner=alice, visibility=Visibility.PUBLIC)
    client = _client(alice)

    percent = client.get("/api/ingredients/?search=100%")
    assert {r["name"] for r in percent.data["results"]} == {"100% Juice"}

    underscore = client.get("/api/ingredients/?search=Apple_Pie")
    assert {r["name"] for r in underscore.data["results"]} == {"Apple_Pie Spice"}
