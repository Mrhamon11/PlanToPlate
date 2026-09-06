"""Meal-planner visibility & IDOR matrix (``Plan/08-Meal-Planner/test-plan.md``, "Security").

*"A planner that suggests a dish you cannot see is a data leak wearing a friendly hat."* The
same rule at the API edge: a profile is private to its owner, a plan never leaks a dish name
the viewer cannot see, and ``profile_snapshot`` / ``seed`` are server-generated only.
"""

from __future__ import annotations

import time

import pytest
from rest_framework.test import APIClient

from planner.models import MealPlan, MealPlanEntry, MealPlanProfile

pytestmark = pytest.mark.django_db

_START = "2026-03-02"


def _client(user):
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def pool(make_dish, make_recipe, add_component):
    def _make(owner, count=8):
        for i in range(count):
            dish = make_dish(f"{owner.username} dish {i}", owner=owner)
            add_component(dish, make_recipe(f"{owner.username} recipe {i}", owner=owner))

    return _make


def _profile(owner, **kwargs):
    defaults = {"owner": owner, "name": "P", "source_scope": "MINE", "no_repeat_days": 0}
    defaults.update(kwargs)
    return MealPlanProfile.objects.create(**defaults)


def _persist(client, profile, seed=1):
    return client.post(
        "/api/planner/plans/",
        {"profile": profile.pk, "start_date": _START, "seed": seed},
        format="json",
    )


# --- plan IDOR matrix ------------------------------------------------------------------


def test_plan_idor_matrix(alice, carol):
    private = MealPlan.objects.create(
        owner=alice, name="Private", start_date="2026-01-05", days=1, seed=1, visibility="PRIVATE"
    )
    shared = MealPlan.objects.create(
        owner=alice, name="Shared", start_date="2026-01-05", days=1, seed=1, visibility="SHARED"
    )
    shared.shared_with.add(carol)
    public = MealPlan.objects.create(
        owner=alice, name="Public", start_date="2026-01-05", days=1, seed=1, visibility="PUBLIC"
    )
    mine = MealPlan.objects.create(
        owner=carol, name="Carol own", start_date="2026-01-05", days=1, seed=1
    )
    shared_entry = MealPlanEntry.objects.create(plan=shared, day_index=0, slot="DINNER")

    carol_client = _client(carol)

    assert carol_client.get(f"/api/planner/plans/{private.pk}/").status_code == 404
    assert carol_client.get(f"/api/planner/plans/{shared.pk}/").status_code == 200
    assert carol_client.get(f"/api/planner/plans/{public.pk}/").status_code == 200

    listed = {row["id"] for row in carol_client.get("/api/planner/plans/").data["results"]}
    assert listed == {shared.pk, public.pk, mine.pk}

    # shared → readable, not writable; private → 404 on write, not 403
    assert (
        carol_client.patch(
            f"/api/planner/plans/{shared.pk}/", {"name": "hijacked"}, format="json"
        ).status_code
        == 403
    )
    assert (
        carol_client.patch(
            f"/api/planner/plans/{private.pk}/", {"name": "hijacked"}, format="json"
        ).status_code
        == 404
    )
    assert carol_client.post(
        f"/api/planner/plans/{shared.pk}/regenerate/", {}, format="json"
    ).status_code in (403, 400)

    # a shared-plan reader must not be able to pull the owner's aggregated ingredient list
    assert (
        carol_client.get(f"/api/planner/plans/{shared.pk}/preview-shopping-list/").status_code
        == 403
    )

    # a read-only sharee cannot mutate an entry of a shared plan either — swap/lock/clear
    assert (
        carol_client.patch(
            f"/api/planner/plans/{shared.pk}/entries/{shared_entry.pk}/",
            {"is_locked": True},
            format="json",
        ).status_code
        == 403
    )
    assert carol_client.post(
        f"/api/planner/plans/{shared.pk}/entries/{shared_entry.pk}/reroll/", {}, format="json"
    ).status_code in (403, 400)
    shared_entry.refresh_from_db()
    assert shared_entry.is_locked is False


def test_shared_plan_hides_invisible_dish_names(alice, carol, pool):
    pool(alice)
    profile = _profile(alice)
    created = _persist(_client(alice), profile).data
    plan = MealPlan.objects.get(pk=created["id"])
    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    plan.shared_with.add(carol)

    response = _client(carol).get(f"/api/planner/plans/{plan.pk}/")

    assert response.status_code == 200
    # every entry's dish belongs to alice and is private → carol sees the slot but no name
    assert all(entry["dish_name"] is None for entry in response.data["entries"])


def test_shared_plan_hides_profile_snapshot_from_readers(alice, carol, pool, make_ingredient):
    """The snapshot embeds the owner's ``excluded_ingredients`` — their allergy list
    (ARCHITECTURE §5 gear 5) — plus the profile name and tag limits. A sharee or a viewer of
    a PUBLIC plan must get ``{}`` for it, never the owner's data (D35).
    """
    pool(alice)
    peanut = make_ingredient("Peanut", owner=alice)
    profile = _profile(alice, name="Alice private profile")
    profile.excluded_ingredients.add(peanut)
    plan = MealPlan.objects.get(pk=_persist(_client(alice), profile).data["id"])
    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    plan.shared_with.add(carol)

    owner_view = _client(alice).get(f"/api/planner/plans/{plan.pk}/")
    assert owner_view.data["profile_snapshot"]["name"] == "Alice private profile"
    assert owner_view.data["profile_snapshot"]["excluded_ingredients"] == ["Peanut"]

    sharee_view = _client(carol).get(f"/api/planner/plans/{plan.pk}/")
    assert sharee_view.status_code == 200
    assert not sharee_view.data["profile_snapshot"]

    plan.visibility = "PUBLIC"
    plan.save(update_fields=["visibility"])
    public_view = _client(carol).get(f"/api/planner/plans/{plan.pk}/")
    assert not public_view.data["profile_snapshot"]


def test_plan_copy_action_is_blocked(alice, carol, pool, make_ingredient):
    """``OwnedViewSetMixin.copy`` transfers ownership; on a ``MealPlan`` that hands the copier
    the owner's ``profile_snapshot`` (allergy list / tag limits / profile name — owner-only on
    read, D35) and a live FK into their private ``MealPlanProfile``. Plan-copy is out of scope
    (D44) — the inherited action must be rejected and write nothing.
    """
    pool(alice)
    peanut = make_ingredient("Peanut", owner=alice)
    profile = _profile(alice, name="Alice SECRET profile")
    profile.excluded_ingredients.add(peanut)
    plan = MealPlan.objects.get(pk=_persist(_client(alice), profile).data["id"])
    plan.visibility = "PUBLIC"
    plan.save(update_fields=["visibility"])

    before = MealPlan.objects.count()
    response = _client(carol).post(f"/api/planner/plans/{plan.pk}/copy/", {}, format="json")

    assert response.status_code in (404, 405)
    assert MealPlan.objects.count() == before

    # the action is gone, not merely gated — the owner cannot reach it either
    owner_response = _client(alice).post(f"/api/planner/plans/{plan.pk}/copy/", {}, format="json")
    assert owner_response.status_code in (404, 405)
    assert MealPlan.objects.count() == before


# --- profile privacy ------------------------------------------------------------------


def test_profile_is_private_to_owner(alice, bob):
    profile = _profile(alice)

    assert _client(bob).get(f"/api/planner/profiles/{profile.pk}/").status_code == 404
    assert _client(bob).get("/api/planner/profiles/").data["results"] == []
    assert (
        _client(bob)
        .patch(f"/api/planner/profiles/{profile.pk}/", {"days": 1}, format="json")
        .status_code
        == 404
    )
    # the viewset relies entirely on get_queryset() scoping — an unauthenticated request must
    # still be rejected outright, never fall through to an empty list
    assert APIClient().get("/api/planner/profiles/").status_code in (401, 403)
    assert APIClient().get(f"/api/planner/profiles/{profile.pk}/").status_code in (401, 403)


def test_cannot_generate_from_others_profile(alice, bob, pool):
    pool(bob)
    alice_profile = _profile(alice)

    response = _client(bob).post(
        "/api/planner/plans/generate/",
        {"profile": alice_profile.pk, "start_date": _START},
        format="json",
    )

    assert response.status_code == 400
    assert MealPlan.objects.count() == 0


# --- manual swap is visibility-checked ------------------------------------------------


def test_cannot_swap_in_invisible_dish(alice, bob, pool, make_dish, make_recipe, add_component):
    pool(alice)
    profile = _profile(alice)
    created = _persist(_client(alice), profile).data
    entry = created["entries"][0]

    secret = make_dish("Bob secret", owner=bob, visibility="PRIVATE")
    add_component(secret, make_recipe("Bob secret recipe", owner=bob))

    response = _client(alice).patch(
        f"/api/planner/plans/{created['id']}/entries/{entry['id']}/",
        {"dish": secret.pk},
        format="json",
    )

    assert response.status_code == 400
    assert MealPlanEntry.objects.get(pk=entry["id"]).dish_id != secret.pk


# --- server-generated snapshot -------------------------------------------------------


def test_cannot_inject_profile_snapshot(alice, pool):
    pool(alice)
    profile = _profile(alice, name="Real")
    client = _client(alice)

    created = client.post(
        "/api/planner/plans/",
        {
            "profile": profile.pk,
            "start_date": _START,
            "seed": 5,
            "profile_snapshot": {"days": 99, "injected": True},
            "seed_injected": 123,
        },
        format="json",
    )

    assert created.status_code == 201
    plan = MealPlan.objects.get(pk=created.data["id"])
    assert "injected" not in plan.profile_snapshot
    assert plan.profile_snapshot["name"] == "Real"
    assert plan.seed == 5

    patched = client.patch(
        f"/api/planner/plans/{plan.pk}/",
        {"profile_snapshot": {"tampered": True}, "seed": 777},
        format="json",
    )
    assert patched.status_code == 200
    plan.refresh_from_db()
    assert "tampered" not in plan.profile_snapshot
    assert plan.seed == 5


# --- generation is time-bounded -----------------------------------------------------


def test_generation_time_bounded(alice, pool):
    pool(alice, count=6)
    hostile = _profile(
        alice,
        name="Hostile",
        days=7,
        tag_limits={f"t{i}": 0 for i in range(30)},
        no_repeat_days=365,
    )

    start = time.monotonic()
    response = _client(alice).post(
        "/api/planner/plans/generate/",
        {"profile": hostile.pk, "start_date": _START},
        format="json",
    )
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed < 5.0
