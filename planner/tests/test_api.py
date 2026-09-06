"""Meal-planner API surface (``Plan/08-Meal-Planner/test-plan.md``, "API").

The IDOR / visibility matrix lives in ``test_security.py``; this covers the preview → persist
→ regenerate → reroll → manual-swap flow and profile CRUD.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from planner.models import MealPlan, MealPlanEntry, MealPlanProfile

pytestmark = pytest.mark.django_db

_START = "2026-03-02"


@pytest.fixture
def client_for(alice, bob):
    """``client_for(username="alice")`` → an ``APIClient`` logged in as the shared ``alice`` /
    ``bob`` fixture (reused so it does not collide with the ``make_*`` fixtures, which are all
    anchored on ``alice``).
    """
    users = {"alice": alice, "bob": bob}

    def _client(*, username="alice"):
        user = users[username]
        client = APIClient()
        client.force_login(user)
        return client, user

    return _client


@pytest.fixture
def pool(make_dish, make_recipe, add_component):
    def _make(owner, count=10):
        dishes = []
        for i in range(count):
            dish = make_dish(f"Pool dish {i}", owner=owner)
            add_component(dish, make_recipe(f"Pool recipe {i}", owner=owner))
            dishes.append(dish)
        return dishes

    return _make


@pytest.fixture
def profile(make_profile):
    def _make(owner):
        return make_profile(owner=owner, source_scope="MINE", name="Weekdays")

    return _make


# --- generate (preview) --------------------------------------------------------------------


def test_generate_returns_preview(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)

    response = client.post(
        "/api/planner/plans/generate/",
        {"profile": prof.pk, "start_date": _START},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert len(response.data["entries"]) == prof.days
    assert "seed" in response.data
    assert MealPlan.objects.count() == 0
    assert MealPlanEntry.objects.count() == 0


def test_generate_accepts_seed(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)

    first = client.post(
        "/api/planner/plans/generate/",
        {"profile": prof.pk, "start_date": _START, "seed": 12345},
        format="json",
    )
    second = client.post(
        "/api/planner/plans/generate/",
        {"profile": prof.pk, "start_date": _START, "seed": 12345},
        format="json",
    )

    assert first.data["seed"] == 12345
    assert [e["dish"] for e in first.data["entries"]] == [e["dish"] for e in second.data["entries"]]


@pytest.mark.parametrize("bad", ["not-a-number", -1, 2**63, 1.5])
def test_invalid_seed_rejected(client_for, pool, profile, bad):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)

    response = client.post(
        "/api/planner/plans/generate/",
        {"profile": prof.pk, "start_date": _START, "seed": bad},
        format="json",
    )

    assert response.status_code == 400


# --- persist -----------------------------------------------------------------------------


def test_persist_plan(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)

    response = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 999, "name": "My week"},
        format="json",
    )

    assert response.status_code == 201, response.data
    plan = MealPlan.objects.get(pk=response.data["id"])
    assert plan.owner == alice
    assert plan.seed == 999
    assert plan.name == "My week"
    assert plan.days == prof.days
    assert plan.entries.count() == prof.days
    assert plan.profile_snapshot["name"] == "Weekdays"


@pytest.mark.parametrize("bad_days", [0, 8, 500, 32767])
def test_patch_days_is_bounded(client_for, pool, profile, bad_days):
    """`MealPlan.days` is bounded 1–7 at the serializer boundary — an unbounded PATCH would
    have `reconcile_entries` bulk-create days x slots unfilled rows (reviewer finding 2).
    """
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 1},
        format="json",
    ).data

    response = client.patch(
        f"/api/planner/plans/{created['id']}/", {"days": bad_days}, format="json"
    )

    assert response.status_code == 400
    plan = MealPlan.objects.get(pk=created["id"])
    assert plan.days == prof.days
    assert plan.entries.count() == prof.days


def test_patch_days_within_range_reconciles(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)  # 7 days
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 1},
        format="json",
    ).data

    response = client.patch(f"/api/planner/plans/{created['id']}/", {"days": 3}, format="json")

    assert response.status_code == 200
    plan = MealPlan.objects.get(pk=created["id"])
    assert plan.days == 3
    assert plan.entries.count() == 3


# --- regenerate ------------------------------------------------------------------------


def test_regenerate_respects_locks(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 1},
        format="json",
    ).data
    plan_id = created["id"]

    locked = next(e for e in created["entries"] if e["dish"] is not None)
    client.patch(
        f"/api/planner/plans/{plan_id}/entries/{locked['id']}/",
        {"is_locked": True},
        format="json",
    )

    response = client.post(f"/api/planner/plans/{plan_id}/regenerate/", {"seed": 2}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["id"] == plan_id
    assert MealPlan.objects.count() == 1
    still = next(e for e in response.data["entries"] if e["id"] == locked["id"])
    assert still["dish"] == locked["dish"]
    assert still["is_locked"] is True
    assert response.data["seed"] == 2


# --- reroll one slot -----------------------------------------------------------------


def test_reroll_single_entry(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice, count=14)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 7},
        format="json",
    ).data
    plan_id = created["id"]
    target = created["entries"][0]
    before = {e["id"]: e["dish"] for e in created["entries"] if e["id"] != target["id"]}

    response = client.post(
        f"/api/planner/plans/{plan_id}/entries/{target['id']}/reroll/", {}, format="json"
    )

    assert response.status_code == 200, response.data
    after = {
        e.pk: e.dish_id
        for e in MealPlanEntry.objects.filter(plan_id=plan_id).exclude(pk=target["id"])
    }
    assert after == before


# --- manual swap -----------------------------------------------------------------------


def test_manual_swap_entry(client_for, pool, profile, make_dish, make_recipe, add_component):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)
    swap_in = make_dish("Hand picked", owner=alice)
    add_component(swap_in, make_recipe("Hand picked recipe", owner=alice))

    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 3},
        format="json",
    ).data
    entry = created["entries"][0]

    response = client.patch(
        f"/api/planner/plans/{created['id']}/entries/{entry['id']}/",
        {"dish": swap_in.pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["dish"] == swap_in.pk
    assert MealPlanEntry.objects.get(pk=entry["id"]).dish_id == swap_in.pk


def test_clear_entry(client_for, pool, profile):
    client, alice = client_for(username="alice")
    pool(alice)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 3},
        format="json",
    ).data
    entry = next(e for e in created["entries"] if e["dish"] is not None)

    response = client.patch(
        f"/api/planner/plans/{created['id']}/entries/{entry['id']}/",
        {"dish": None},
        format="json",
    )

    assert response.status_code == 200
    assert MealPlanEntry.objects.get(pk=entry["id"]).dish_id is None


# --- shopping list -------------------------------------------------------------------


@pytest.fixture
def dish_with_ingredient(make_dish, make_recipe, add_component, add_ingredient, make_ingredient):
    def _make(name, owner):
        dish = make_dish(name, owner=owner)
        recipe = make_recipe(f"{name} recipe", owner=owner)
        add_component(dish, recipe)
        add_ingredient(recipe, make_ingredient(f"{name} ingredient"), quantity="200")
        return dish

    return _make


def test_preview_shopping_list_writes_nothing(client_for, profile, dish_with_ingredient):
    from lists.models import ListItem

    client, alice = client_for(username="alice")
    dish_with_ingredient("Soup", alice)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 1},
        format="json",
    ).data

    before = ListItem.objects.count()
    response = client.get(f"/api/planner/plans/{created['id']}/preview-shopping-list/")

    assert response.status_code == 200
    assert "lines" in response.data
    assert ListItem.objects.count() == before


def test_generate_shopping_list_populates_a_list(client_for, profile, dish_with_ingredient):
    client, alice = client_for(username="alice")
    dish_with_ingredient("Stew", alice)
    prof = profile(alice)
    created = client.post(
        "/api/planner/plans/",
        {"profile": prof.pk, "start_date": _START, "seed": 1},
        format="json",
    ).data

    response = client.post(
        f"/api/planner/plans/{created['id']}/generate-shopping-list/", {}, format="json"
    )

    assert response.status_code == 200, response.data
    plan = MealPlan.objects.get(pk=created["id"])
    assert plan.shopping_list is not None
    assert plan.shopping_list.items.filter(source="GENERATED").exists()


# --- profile CRUD --------------------------------------------------------------------


def test_profile_crud(client_for):
    client, alice = client_for(username="alice")

    created = client.post(
        "/api/planner/profiles/",
        {"name": "Weekend", "days": 2, "slots": ["LUNCH", "DINNER"], "favorites_bias": "2.0"},
        format="json",
    )
    assert created.status_code == 201, created.data
    profile_id = created.data["id"]

    listed = client.get("/api/planner/profiles/")
    assert profile_id in {row["id"] for row in listed.data["results"]}

    patched = client.patch(f"/api/planner/profiles/{profile_id}/", {"days": 3}, format="json")
    assert patched.status_code == 200
    assert MealPlanProfile.objects.get(pk=profile_id).days == 3

    deleted = client.delete(f"/api/planner/profiles/{profile_id}/")
    assert deleted.status_code == 204
    assert not MealPlanProfile.objects.filter(pk=profile_id).exists()


def test_profile_rejects_empty_slots(client_for):
    client, alice = client_for(username="alice")

    response = client.post(
        "/api/planner/profiles/",
        {"name": "Broken", "slots": []},
        format="json",
    )

    assert response.status_code == 400
    assert "slots" in response.data


def test_setting_a_second_default_clears_the_first(client_for):
    client, alice = client_for(username="alice")
    first = client.post(
        "/api/planner/profiles/",
        {"name": "A", "is_default": True, "slots": ["DINNER"]},
        format="json",
    ).data
    client.post(
        "/api/planner/profiles/",
        {"name": "B", "is_default": True, "slots": ["DINNER"]},
        format="json",
    )

    assert MealPlanProfile.objects.filter(owner=alice, is_default=True).count() == 1
    assert not MealPlanProfile.objects.get(pk=first["id"]).is_default
