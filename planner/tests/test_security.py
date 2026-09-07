"""Meal-planner visibility & IDOR matrix (``Plan/08-Meal-Planner/test-plan.md``, "Security").

*"A planner that suggests a dish you cannot see is a data leak wearing a friendly hat."* The
same rule at the API edge: a profile is private to its owner, a plan never leaks a dish name
the viewer cannot see, and ``profile_snapshot`` / ``seed`` are server-generated only.
"""

from __future__ import annotations

import time

import pytest
from django.test import Client
from rest_framework.test import APIClient

from catalog.models import Ingredient
from core.services.sharing import SharingError, share, unshare
from meals.models import Dish
from planner.models import MealPlan, MealPlanEntry, MealPlanProfile
from recipes.models import Recipe

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
    # a read-only sharee cannot write the owner's shopping list from the plan either
    assert (
        carol_client.post(
            f"/api/planner/plans/{shared.pk}/generate-shopping-list/", {}, format="json"
        ).status_code
        == 403
    )

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


# --- plan delete / share are owner-only (B8 / B9) ----------------------------------


def test_plan_bulk_delete_ignores_unowned_ids(alice, carol):
    """The HTML bulk-delete endpoint filters every id through ``visible_to(user).filter(
    owner=user)`` — another user's id in the payload is ignored, never an error (B8)."""
    mine = MealPlan.objects.create(
        owner=carol, name="Mine", start_date="2026-01-05", days=1, seed=1
    )
    theirs = MealPlan.objects.create(
        owner=alice, name="Theirs", start_date="2026-01-05", days=1, seed=1
    )

    client = Client()
    client.force_login(carol)
    response = client.post("/planner/plans/delete/", {"ids": [mine.pk, theirs.pk], "confirm": "1"})

    assert response.status_code == 302
    assert not MealPlan.objects.filter(pk=mine.pk).exists()
    assert MealPlan.objects.filter(pk=theirs.pk).exists()


def test_plan_share_is_owner_only(alice, carol, bob):
    """A read-only sharee cannot re-share or unshare the plan (B9)."""
    plan = MealPlan.objects.create(
        owner=alice, name="P", start_date="2026-01-05", days=1, seed=1, visibility="SHARED"
    )
    plan.shared_with.add(carol)

    client = Client()
    client.force_login(carol)

    assert (
        client.post(f"/planner/plans/{plan.pk}/share/", {"visibility": "PUBLIC"}).status_code == 403
    )
    assert client.post(f"/planner/plans/{plan.pk}/unshare/", {"users": [bob.pk]}).status_code == 403
    plan.refresh_from_db()
    assert plan.visibility == "SHARED"


def test_plan_rename_is_owner_only(alice, carol):
    """B4 — the HTML rename endpoint resolves through ``_owned_plan``: another user's private
    plan is a 404, a shared plan a 403, and the name never changes."""
    private = MealPlan.objects.create(
        owner=alice, name="Private", start_date="2026-01-05", days=1, seed=1
    )
    shared = MealPlan.objects.create(
        owner=alice, name="Shared", start_date="2026-01-05", days=1, seed=1, visibility="SHARED"
    )
    shared.shared_with.add(carol)

    client = Client()
    client.force_login(carol)

    assert client.get(f"/planner/plans/{private.pk}/rename/").status_code == 404
    assert client.post(f"/planner/plans/{private.pk}/rename/", {"name": "x"}).status_code == 404
    assert client.get(f"/planner/plans/{shared.pk}/rename/").status_code == 403
    assert client.post(f"/planner/plans/{shared.pk}/rename/", {"name": "x"}).status_code == 403

    private.refresh_from_db()
    shared.refresh_from_db()
    assert private.name == "Private"
    assert shared.name == "Shared"


# --- sharing a plan cascades read to its dishes / recipes (08.20 B1) -----------------


def _plan_with_dishes(owner, dishes):
    plan = MealPlan.objects.create(
        owner=owner,
        name="Week",
        start_date="2026-03-02",
        days=len(dishes),
        seed=1,
        profile_snapshot={"slots": ["DINNER"]},
    )
    for day, dish in enumerate(dishes):
        MealPlanEntry.objects.create(plan=plan, day_index=day, slot="DINNER", dish=dish)
    return plan


def test_sharing_a_plan_cascades_read_to_its_dishes_and_recipes(
    alice,
    carol,
    make_dish,
    make_recipe,
    add_component,
    add_ingredient,
    add_sub_recipe,
    make_ingredient,
):
    """hamon shares a plan whose dinners are hamon-owned private dishes; afterwards each
    dish, its component recipes, their sub-recipes and ingredients are visible_to(avi), and
    the plan-detail grid renders the dish names as working links."""
    allergen = make_ingredient("Alice Peanut", owner=alice, visibility="PRIVATE")
    sub = make_recipe("Alice Sub", owner=alice, visibility="PRIVATE")
    add_ingredient(sub, allergen)
    main = make_recipe("Alice Main", owner=alice, visibility="PRIVATE")
    add_sub_recipe(main, sub)
    dish = make_dish("Alice Dinner", owner=alice, visibility="PRIVATE")
    add_component(dish, main)
    plan = _plan_with_dishes(alice, [dish])

    share(plan, actor=alice, users=[carol])

    assert MealPlan.objects.visible_to(carol).filter(pk=plan.pk).exists()
    assert Dish.objects.visible_to(carol).filter(pk=dish.pk).exists()
    assert Recipe.objects.visible_to(carol).filter(pk=main.pk).exists()
    assert Recipe.objects.visible_to(carol).filter(pk=sub.pk).exists()
    assert Ingredient.objects.visible_to(carol).filter(pk=allergen.pk).exists()

    client = Client()
    client.force_login(carol)
    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()
    assert f'<a href="{dish.get_absolute_url()}">{dish.name}</a>' in body
    assert "A dish shared privately" not in body


def test_sharing_a_plan_with_an_ungrantable_dish_is_refused(
    alice, bob, carol, make_dish, make_recipe, add_component
):
    """A dish owned by a third user that the recipient cannot see refuses the whole share,
    names the dish, and adds nothing to any ``shared_with`` (no partial state)."""
    foreign = make_dish("Bob Secret", owner=bob, visibility="PRIVATE")
    add_component(foreign, make_recipe("Bob Secret Recipe", owner=bob, visibility="PRIVATE"))
    mine = make_dish("Alice Dish", owner=alice, visibility="PRIVATE")
    add_component(mine, make_recipe("Alice Recipe", owner=alice, visibility="PRIVATE"))
    plan = _plan_with_dishes(alice, [mine, foreign])

    with pytest.raises(SharingError) as exc:
        share(plan, actor=alice, users=[carol])

    assert "Bob Secret" in str(exc.value)
    assert not MealPlan.objects.visible_to(carol).filter(pk=plan.pk).exists()
    assert carol not in plan.shared_with.all()
    assert carol not in mine.shared_with.all()
    assert carol not in foreign.shared_with.all()


def test_unsharing_a_plan_does_not_revoke_the_cascaded_dish_grants(
    alice, carol, make_dish, make_recipe, add_component
):
    """D31's asymmetry, pinned for plans so it is not later read as a leak: after ``unshare``
    the recipient keeps read on the dishes / recipes the share granted."""
    dish = make_dish("Alice Dinner", owner=alice, visibility="PRIVATE")
    recipe = make_recipe("Alice Recipe", owner=alice, visibility="PRIVATE")
    add_component(dish, recipe)
    plan = _plan_with_dishes(alice, [dish])
    share(plan, actor=alice, users=[carol])

    unshare(plan, actor=alice, users=[carol])

    assert not MealPlan.objects.visible_to(carol).filter(pk=plan.pk).exists()
    assert Dish.objects.visible_to(carol).filter(pk=dish.pk).exists()
    assert Recipe.objects.visible_to(carol).filter(pk=recipe.pk).exists()


def test_plan_share_post_resolves_through_owned_plan(alice, bob, carol):
    """08.19 R2 — ``PlanShareView`` / ``PlanUnshareView`` resolve through ``_owned_plan``:
    a non-owner who cannot see the plan gets a 404 (distinct from
    ``test_plan_share_is_owner_only``, which only covered the shared-sharee 403 path)."""
    private = MealPlan.objects.create(
        owner=alice, name="P", start_date="2026-01-05", days=1, seed=1
    )
    client = Client()
    client.force_login(bob)

    assert (
        client.post(f"/planner/plans/{private.pk}/share/", {"visibility": "PUBLIC"}).status_code
        == 404
    )
    assert (
        client.post(f"/planner/plans/{private.pk}/unshare/", {"users": [carol.pk]}).status_code
        == 404
    )
    private.refresh_from_db()
    assert private.visibility == "PRIVATE"


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
