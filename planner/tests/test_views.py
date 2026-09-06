"""Meal-planner HTML views (``Plan/08-Meal-Planner/test-plan.md``, "UI").

08.11 landed the profile editor; 08.12–08.14 add the generate screen, the saved-plan week
grid (per-slot lock / reroll / manual-swap HTMX), the shopping-list preview and the
empty-state guidance.
"""

from __future__ import annotations

import datetime

import pytest
from django.test import Client

from planner.models import MealPlan, MealPlanEntry, MealPlanProfile
from planner.services.generate import generate_plan
from planner.services.persist import save_plan
from recipes.models import RecipeRole

pytestmark = pytest.mark.django_db

_START = datetime.date(2026, 3, 2)

_GEAR_FIELD_IDS = [
    "id_days",
    "id_slots",
    "id_dish_template",
    "id_source_scope",
    "id_tag_limits",
    "id_excluded_tags",
    "id_excluded_ingredients",
    "id_no_repeat_days",
    "id_min_rating",
    "id_favorites_only",
    "id_favorites_bias",
    "id_max_total_minutes",
]


@pytest.fixture
def client_as(user_factory, django_user_model):
    def _login(**kwargs):
        username = kwargs.get("username")
        user = None
        if username:
            user = django_user_model.objects.filter(username=username).first()
        if user is None:
            user = user_factory(**kwargs)
        client = Client()
        client.force_login(user)
        return client, user

    return _login


def test_profile_form_renders_all_gears(client_as):
    client, alice = client_as(username="alice")

    response = client.get("/planner/profiles/new/")

    assert response.status_code == 200
    body = response.content.decode()
    for field_id in _GEAR_FIELD_IDS:
        assert field_id in body, field_id
    for section in ("When", "What", "Limits", "Quality"):
        assert section in body


def test_profile_form_requires_login(client):
    response = client.get("/planner/profiles/new/")
    assert response.status_code == 302
    assert "/accounts/login" in response["Location"]


def test_create_profile(client_as):
    client, alice = client_as(username="alice")

    response = client.post(
        "/planner/profiles/new/",
        {
            "name": "Weeknights",
            "days": 5,
            "slots": ["DINNER"],
            "dish_template": "BALANCED",
            "source_scope": "SHARED",
            "tag_limits": '{"chicken": 1}',
            "no_repeat_days": 14,
            "favorites_bias": "1.5",
            "exclude_staples": "on",
        },
    )

    assert response.status_code == 302
    profile = MealPlanProfile.objects.get(owner=alice)
    assert profile.name == "Weeknights"
    assert profile.days == 5
    assert profile.slots == ["DINNER"]
    assert profile.tag_limits == {"chicken": 1}


def test_create_profile_rejects_empty_slots(client_as):
    client, alice = client_as(username="alice")

    response = client.post(
        "/planner/profiles/new/",
        {"name": "Broken", "days": 5, "dish_template": "BALANCED", "source_scope": "MINE"},
    )

    assert response.status_code == 200
    assert not MealPlanProfile.objects.filter(owner=alice).exists()
    assert "at least one meal slot" in response.content.decode()


def test_blank_no_repeat_days_falls_back_to_design_default(client_as):
    """A cleared ``no_repeat_days`` must fall back to the design default (14), not 0 — 0
    silently disables no-repeat protection (08 reviewer finding).
    """
    client, alice = client_as(username="alice")

    response = client.post(
        "/planner/profiles/new/",
        {
            "name": "Defaulted",
            "days": 5,
            "slots": ["DINNER"],
            "dish_template": "BALANCED",
            "source_scope": "SHARED",
            "favorites_bias": "1.5",
        },
    )

    assert response.status_code == 302
    profile = MealPlanProfile.objects.get(owner=alice, name="Defaulted")
    assert profile.no_repeat_days == 14


def test_explicit_zero_no_repeat_days_is_preserved(client_as):
    """0 typed on purpose means "no window" and must survive — only a blank falls back."""
    client, alice = client_as(username="alice")

    response = client.post(
        "/planner/profiles/new/",
        {
            "name": "No window",
            "days": 5,
            "slots": ["DINNER"],
            "dish_template": "BALANCED",
            "source_scope": "SHARED",
            "no_repeat_days": 0,
            "favorites_bias": "1.5",
        },
    )

    assert response.status_code == 302
    assert MealPlanProfile.objects.get(owner=alice, name="No window").no_repeat_days == 0


def test_profile_list_is_scoped_to_owner(client_as):
    client, alice = client_as(username="alice")
    mine = MealPlanProfile.objects.create(owner=alice, name="Mine")

    other_client, bob = client_as(username="bob")
    MealPlanProfile.objects.create(owner=bob, name="Bob only")

    response = client.get("/planner/profiles/")
    body = response.content.decode()
    assert "Mine" in body
    assert "Bob only" not in body
    assert response.status_code == 200
    assert list(response.context["profiles"]) == [mine]


def test_cannot_edit_another_users_profile(client_as):
    _client_a, alice = client_as(username="alice")
    profile = MealPlanProfile.objects.create(owner=alice, name="Alice")

    bob_client, _bob = client_as(username="bob")
    assert bob_client.get(f"/planner/profiles/{profile.pk}/").status_code == 404


# =====================================================================================
# Generate screen + plan grid (08.12)
# =====================================================================================


@pytest.fixture
def dish_pool(make_dish, make_recipe, add_component):
    def _make(owner, count=8):
        dishes = []
        for i in range(count):
            dish = make_dish(f"{owner.username} dish {i}", owner=owner)
            add_component(dish, make_recipe(f"{owner.username} recipe {i}", owner=owner))
            dishes.append(dish)
        return dishes

    return _make


@pytest.fixture
def saved_plan(dish_pool, db):
    def _make(owner, *, days=3, slots=("DINNER",)):
        dish_pool(owner)
        profile = MealPlanProfile.objects.create(
            owner=owner,
            name="P",
            source_scope="MINE",
            slots=list(slots),
            no_repeat_days=0,
            dish_template="ONE_POT",
        )
        result = generate_plan(owner, profile, seed=42, days=days, slots=list(slots))
        return save_plan(owner, result, profile=profile, start_date=_START, days=days)

    return _make


def test_plan_grid_renders(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=3)

    response = client.get(f"/planner/plans/{plan.pk}/")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="plan-grid"' in body
    assert body.count('<div id="slot-') == 3  # one card per day/slot
    for day in ("Day 1", "Day 2", "Day 3"):
        assert day in body


def test_grid_orders_slots_breakfast_lunch_dinner(client_as, saved_plan):
    """MealPlanEntry.Meta.ordering sorts slot alphabetically (BREAKFAST, DINNER, LUNCH); the
    grid must impose chronological order instead (08.12 carried review finding).
    """
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1, slots=("BREAKFAST", "LUNCH", "DINNER"))

    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()
    positions = [body.index(label) for label in ("Breakfast", "Lunch", "Dinner")]
    assert positions == sorted(positions)


def test_unfilled_slot_shows_reason_inline(client_as, make_dish, make_recipe, add_component):
    client, alice = client_as(username="alice")
    # exactly one dish, seven dinners → six unfilled slots, each carrying a reason
    dish = make_dish("Only one", owner=alice)
    add_component(dish, make_recipe("Only one recipe", owner=alice))
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )

    response = client.post(
        "/planner/plans/new/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 7, "seed": 5},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "slot-card-reason" in body
    assert "Not enough distinct dishes" in body


def test_preview_seed_round_trips_into_save(client_as, dish_pool):
    """The preview carries its seed into the persist form so "save exactly what I previewed"
    holds (08.12 carried note).
    """
    client, alice = client_as(username="alice")
    dish_pool(alice)
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )

    preview = client.post(
        "/planner/plans/new/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 3, "seed": 777},
    )
    assert preview.status_code == 200
    assert 'name="seed" value="777"' in preview.content.decode()

    saved = client.post(
        "/planner/plans/save/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 3, "seed": 777},
    )
    assert saved.status_code == 302
    plan = MealPlan.objects.get(owner=alice)
    assert plan.seed == 777
    assert plan.days == 3


def test_lock_toggle_htmx(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=3)
    entry = plan.entries.filter(dish__isnull=False).first()

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/lock/", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="plan-grid"' not in body  # just the one card, not the whole page
    assert f'id="slot-{entry.pk}"' in body
    assert "Unlock" in body
    entry.refresh_from_db()
    assert entry.is_locked is True


def test_reroll_htmx_updates_one_card(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=4)
    entries = list(plan.entries.order_by("day_index"))
    target = entries[0]
    others_before = {e.pk: e.dish_id for e in entries[1:]}

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{target.pk}/reroll/", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    assert f'id="slot-{target.pk}"' in response.content.decode()
    after = {e.pk: e.dish_id for e in MealPlanEntry.objects.filter(plan=plan).exclude(pk=target.pk)}
    assert after == others_before


def test_manual_swap_is_visibility_checked(
    client_as, saved_plan, make_dish, make_recipe, add_component, user_factory
):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)
    entry = plan.entries.first()
    bob = user_factory(username="bob")
    secret = make_dish("Bob secret", owner=bob, visibility="PRIVATE")
    add_component(secret, make_recipe("Bob secret recipe", owner=bob))

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/swap/",
        {"dish": secret.pk},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 404
    entry.refresh_from_db()
    assert entry.dish_id != secret.pk


def test_plan_grid_write_actions_forbidden_for_sharee(client_as, saved_plan, user_factory):
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)
    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    carol = user_factory(username="carol")
    plan.shared_with.add(carol)
    entry = plan.entries.first()

    carol_client = Client()
    carol_client.force_login(carol)

    assert carol_client.get(f"/planner/plans/{plan.pk}/").status_code == 200
    assert (
        carol_client.post(f"/planner/plans/{plan.pk}/entries/{entry.pk}/lock/").status_code == 403
    )
    assert carol_client.post(f"/planner/plans/{plan.pk}/regenerate/").status_code == 403


# =====================================================================================
# days-change confirmation (08.12)
# =====================================================================================


def test_reducing_days_asks_before_dropping_entries(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=5)

    confirm = client.get(f"/planner/plans/{plan.pk}/days/?days=2", HTTP_HX_REQUEST="true")

    assert confirm.status_code == 200
    body = confirm.content.decode()
    assert "modal" in body
    assert "removed" in body.lower()
    # nothing dropped yet
    assert plan.entries.count() == 5

    applied = client.post(f"/planner/plans/{plan.pk}/days/", {"days": 2})
    assert applied.status_code == 302
    plan.refresh_from_db()
    assert plan.days == 2
    assert plan.entries.count() == 2


def test_growing_days_adds_empty_cells(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)

    client.post(f"/planner/plans/{plan.pk}/days/", {"days": 4})

    plan.refresh_from_db()
    assert plan.days == 4
    assert plan.entries.count() == 4
    assert plan.entries.filter(day_index=3, dish__isnull=True).exists()


# =====================================================================================
# shopping-list preview (08.13)
# =====================================================================================


@pytest.fixture
def plan_with_ingredients(
    make_dish, make_recipe, add_component, add_ingredient, make_ingredient, db
):
    def _make(owner, *, staple=False):
        dish = make_dish("Soup", owner=owner)
        recipe = make_recipe("Soup recipe", owner=owner)
        add_component(dish, recipe)
        add_ingredient(
            recipe, make_ingredient("Onion", owner=owner, is_staple=staple), quantity="200"
        )
        profile = MealPlanProfile.objects.create(
            owner=owner,
            name="P",
            source_scope="MINE",
            slots=["DINNER"],
            no_repeat_days=0,
            dish_template="ONE_POT",
        )
        result = generate_plan(owner, profile, seed=1, days=1, slots=["DINNER"])
        return save_plan(owner, result, profile=profile, start_date=_START, days=1)

    return _make


def test_shopping_preview_shows_lines_and_staples_toggle(client_as, plan_with_ingredients):
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice)

    response = client.get(f"/planner/plans/{plan.pk}/shopping/preview/", HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Onion" in body
    assert 'name="exclude_staples"' in body


def test_shopping_preview_warns_when_checked_items_would_be_replaced(
    client_as, plan_with_ingredients
):
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice)
    client.post(f"/planner/plans/{plan.pk}/shopping/generate/")
    plan.refresh_from_db()
    plan.shopping_list.items.update(is_checked=True)

    response = client.get(f"/planner/plans/{plan.pk}/shopping/preview/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "already checked" in body.lower()


def test_shopping_preview_surfaces_invisible_dish_inline_not_500(
    client_as, make_dish, make_recipe, add_component, add_ingredient, make_ingredient, user_factory
):
    """A dish unshared between plan save and preview must show inline, not 500 (08 reviewer
    finding — the HTML twin of ``api.py``'s ``ListVisibilityError`` → 400).
    """
    client, alice = client_as(username="alice")
    bob = user_factory(username="bob")
    dish = make_dish("Bob shared", owner=bob, visibility="SHARED")
    recipe = make_recipe("Bob recipe", owner=bob)
    add_component(dish, recipe)
    add_ingredient(recipe, make_ingredient("Onion", owner=bob), quantity="100")
    dish.shared_with.add(alice)

    profile = MealPlanProfile.objects.create(
        owner=alice, name="P", source_scope="SHARED", slots=["DINNER"], no_repeat_days=0
    )
    plan = MealPlan.objects.create(
        owner=alice, name="W", start_date=_START, days=1, seed=1, profile=profile
    )
    MealPlanEntry.objects.create(plan=plan, day_index=0, slot="DINNER", dish=dish)

    dish.shared_with.remove(alice)

    response = client.get(f"/planner/plans/{plan.pk}/shopping/preview/", HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert "not available to you" in response.content.decode()


def test_generate_shopping_list_from_plan(client_as, plan_with_ingredients):
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice)

    response = client.post(f"/planner/plans/{plan.pk}/shopping/generate/")

    assert response.status_code == 302
    plan.refresh_from_db()
    assert plan.shopping_list is not None
    assert plan.shopping_list.items.filter(source="GENERATED").exists()


# =====================================================================================
# empty-state (08.14)
# =====================================================================================


def test_empty_pool_shows_guidance(client_as):
    """A brand-new user with no dishes gets a route forward, not a blank grid
    (design.md, "Edge cases").
    """
    client, alice = client_as(username="alice")

    index = client.get("/planner/")
    generate = client.get("/planner/plans/new/")

    for response in (index, generate):
        assert response.status_code == 200
        body = response.content.decode()
        assert "empty-pool" in body
        assert "/dishes/new/" in body


def test_empty_pool_when_scope_excludes_everything(client_as, dish_pool, user_factory):
    """Dishes exist but none are in scope → still guidance, not a silent all-unfilled grid."""
    client, alice = client_as(username="alice")
    bob = user_factory(username="bob")
    dish_pool(bob)  # alice can't see any of them
    profile = MealPlanProfile.objects.create(
        owner=alice, name="P", source_scope="MINE", slots=["DINNER"], no_repeat_days=0
    )

    response = client.post(
        "/planner/plans/new/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 3},
    )

    assert response.status_code == 200
    assert "empty-pool" in response.content.decode()


def test_mobile_layout_stacks():
    """The week grid is mobile-first: a single column until a breakpoint, then a multi-column
    track (design.md, "Plan grid": "Desktop shows a week grid; mobile stacks vertically").
    """
    css = (
        pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
        / "static"
        / "css"
        / "components.css"
    ).read_text()
    grid_rule = css.split(".plan-grid {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr" in grid_rule
    assert "@media (min-width:" in css.split(".plan-grid {", 1)[1]


def test_auto_composed_slot_is_marked_in_preview(
    client_as, make_recipe, make_ingredient, add_ingredient
):
    client, alice = client_as(username="alice")
    for role in (RecipeRole.PROTEIN, RecipeRole.CARB, RecipeRole.VEGETABLE):
        recipe = make_recipe(f"{role} r", owner=alice, role=role)
        add_ingredient(recipe, make_ingredient(f"{role} i", owner=alice))
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="BALANCED",
    )

    response = client.post(
        "/planner/plans/new/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 1, "seed": 1},
    )

    assert response.status_code == 200
    assert "Auto-composed" in response.content.decode()


def test_composed_slot_keeps_auto_composed_marker_after_slot_action(
    client_as, make_recipe, make_ingredient, add_ingredient
):
    """``render_card`` must set ``entry.is_auto_composed`` the same way ``PlanDetailView`` does,
    or the "Auto-composed" marker vanishes from a composed-dish slot card after any HTMX
    lock / reroll / swap until a full page reload (N1).
    """
    client, alice = client_as(username="alice")
    for role in (RecipeRole.PROTEIN, RecipeRole.CARB, RecipeRole.VEGETABLE):
        recipe = make_recipe(f"{role} r", owner=alice, role=role)
        add_ingredient(recipe, make_ingredient(f"{role} i", owner=alice))
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="BALANCED",
    )
    result = generate_plan(alice, profile, seed=1, days=1, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=1)
    entry = plan.entries.get(day_index=0, slot="DINNER")
    assert entry.dish is not None  # the composed trio was materialised on save

    # the full grid marks it
    assert "Auto-composed" in client.get(f"/planner/plans/{plan.pk}/").content.decode()

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/lock/", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="plan-grid"' not in body  # just the re-rendered card
    assert "Auto-composed" in body
