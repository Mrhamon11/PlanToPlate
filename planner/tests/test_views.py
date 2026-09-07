"""Meal-planner HTML views (``Plan/08-Meal-Planner/test-plan.md``, "UI").

08.11 landed the profile editor; 08.12–08.14 add the generate screen, the saved-plan week
grid (per-slot lock / reroll / manual-swap HTMX), the shopping-list preview and the
empty-state guidance.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.test import Client

from core.services.sharing import share
from lists.models import List
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
            "tag_limits_tag": "chicken",
            "tag_limits_max": "1",
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


def test_manual_swap_clears_lock_html(
    client_as, saved_plan, make_dish, make_recipe, add_component
):
    """The HTML swap path clears ``is_locked`` on a manual swap — pinned so the API twin
    stays aligned with it (owner decision, 08 final rework)."""
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)
    entry = plan.entries.filter(dish__isnull=False).first()
    entry.is_locked = True
    entry.save(update_fields=["is_locked"])
    swap_in = make_dish("Hand picked", owner=alice)
    add_component(swap_in, make_recipe("Hand picked recipe", owner=alice))

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/swap/",
        {"dish": swap_in.pk},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    entry.refresh_from_db()
    assert entry.dish_id == swap_in.pk
    assert entry.is_locked is False


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
    assert (
        carol_client.post(f"/planner/plans/{plan.pk}/entries/{entry.pk}/reroll/").status_code == 403
    )
    assert (
        carol_client.post(
            f"/planner/plans/{plan.pk}/entries/{entry.pk}/swap/", {"dish": ""}
        ).status_code
        == 403
    )
    assert carol_client.post(f"/planner/plans/{plan.pk}/regenerate/").status_code == 403
    assert carol_client.get(f"/planner/plans/{plan.pk}/days/?days=1").status_code == 403
    assert carol_client.get(f"/planner/plans/{plan.pk}/shopping/preview/").status_code == 403
    assert carol_client.post(f"/planner/plans/{plan.pk}/shopping/generate/").status_code == 403
    assert carol_client.get(f"/planner/plans/{plan.pk}/delete/").status_code == 403


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
        assert 'data-testid="empty-pool"' in body
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
    assert 'data-testid="empty-pool"' in response.content.decode()


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


# =====================================================================================
# Dev-test rework (2026-09-07) — subtask 08.16
# =====================================================================================

_BASE_PROFILE_POST = {
    "days": 5,
    "slots": ["DINNER"],
    "dish_template": "BALANCED",
    "source_scope": "SHARED",
    "favorites_bias": "1.5",
}


def test_preview_grid_shows_dish_names(client_as, dish_pool):
    """A generate preview renders the pool dish names (linked for real dishes) and never
    "A dish shared privately" — every preview dish is visible by construction (B1)."""
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

    response = client.post(
        "/planner/plans/new/",
        {"profile": profile.pk, "start_date": _START.isoformat(), "days": 3, "seed": 11},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "A dish shared privately" not in body
    chosen = [
        cell["entry"].dish
        for row in response.context["rows"]
        for cell in row["cells"]
        if cell["entry"] and cell["entry"].dish
    ]
    assert chosen
    for dish in chosen:
        assert dish.name in body
        assert f'href="{dish.get_absolute_url()}"' in body


def test_reroll_htmx_shows_message_when_nothing_changed(
    client_as, make_dish, make_recipe, add_component
):
    """A re-roll that finds no alternative surfaces an info message, not a silent success (B3)."""
    client, alice = client_as(username="alice")
    dish = make_dish("Only one", owner=alice)
    add_component(dish, make_recipe("r", owner=alice))
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )
    result = generate_plan(alice, profile, seed=1, days=1, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=1)
    entry = plan.entries.get()

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/reroll/", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    assert "no other dish fits" in response.content.decode().lower()
    entry.refresh_from_db()
    assert entry.dish_id == dish.pk


def test_shopping_preview_unchecking_staples_includes_them(client_as, plan_with_ingredients):
    """Box unchecked → an explicit "include staples", not a fallback to the profile default
    (B4)."""
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice, staple=True)

    response = client.get(
        f"/planner/plans/{plan.pk}/shopping/preview/",
        {"staples_toggle": "1"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "Onion" in response.content.decode()
    assert response.context["staples_skipped"] == 0


def test_generate_shopping_list_respects_unchecked_staples(client_as, plan_with_ingredients):
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice, staple=True)

    client.post(f"/planner/plans/{plan.pk}/shopping/generate/", {"exclude_staples": "false"})

    plan.refresh_from_db()
    names = [i.ingredient.name for i in plan.shopping_list.items.all() if i.ingredient_id]
    assert "Onion" in names


def test_profile_form_clamps_min_rating(client_as):
    client, alice = client_as(username="alice")

    for name, posted in (("Low", "-5"), ("High", "10"), ("Blank", "")):
        response = client.post(
            "/planner/profiles/new/",
            {**_BASE_PROFILE_POST, "name": name, "min_rating": posted},
        )
        assert response.status_code == 302, posted

    assert MealPlanProfile.objects.get(name="Low").min_rating == 1
    assert MealPlanProfile.objects.get(name="High").min_rating == 5
    assert MealPlanProfile.objects.get(name="Blank").min_rating is None


def test_profile_form_clamps_favorites_bias(client_as):
    client, alice = client_as(username="alice")

    for name, posted in (("Zero", "0"), ("Half", "0.5")):
        response = client.post(
            "/planner/profiles/new/",
            {**_BASE_PROFILE_POST, "name": name, "favorites_bias": posted},
        )
        assert response.status_code == 302, posted

    assert MealPlanProfile.objects.get(name="Zero").favorites_bias == Decimal("1.00")
    assert MealPlanProfile.objects.get(name="Half").favorites_bias == Decimal("1.00")


def test_profile_create_without_touching_favorites_bias(client_as):
    """The "Favorites bias" input renders pre-filled with the model default, so submitting the
    create form without touching it still saves — it is not a silently-required field (08.16).
    """
    client, alice = client_as(username="alice")

    form = client.get("/planner/profiles/new/")
    assert form.status_code == 200
    assert 'name="favorites_bias"' in form.content.decode()
    assert 'value="1.5"' in form.content.decode()

    payload = {k: v for k, v in _BASE_PROFILE_POST.items() if k != "favorites_bias"}
    response = client.post("/planner/profiles/new/", {**payload, "name": "No bias"})

    assert response.status_code == 302
    assert MealPlanProfile.objects.get(name="No bias").favorites_bias == Decimal("1.50")


def test_saved_plan_with_unfilled_slots_shows_reason_banner(
    client_as, make_dish, make_recipe, add_component
):
    client, alice = client_as(username="alice")
    dish = make_dish("Only one", owner=alice)
    add_component(dish, make_recipe("r", owner=alice))
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )
    result = generate_plan(alice, profile, seed=5, days=4, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=4)
    assert plan.entries.filter(dish__isnull=True).exists()

    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()

    assert "reason-banner" in body
    assert "Not enough distinct dishes" in body


def test_saved_plan_all_unfilled_shows_empty_pool_guidance(client_as):
    client, alice = client_as(username="alice")
    profile = MealPlanProfile.objects.create(
        owner=alice, name="P", source_scope="MINE", slots=["DINNER"], no_repeat_days=0
    )
    plan = MealPlan.objects.create(
        owner=alice,
        name="W",
        start_date=_START,
        days=3,
        seed=1,
        profile=profile,
        profile_snapshot={"slots": ["DINNER"]},
    )
    for day in range(3):
        MealPlanEntry.objects.create(plan=plan, day_index=day, slot="DINNER")

    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()

    assert 'data-testid="empty-pool"' in body
    assert "reason-banner" not in body
    # The guidance replaces the grid — an effectively-empty pool must not render a wall of
    # blank "Empty" cards under it (F1; design.md, "Edge cases" / "UI").
    assert 'class="plan-grid"' not in body


def test_regenerate_into_all_unfilled_shows_guidance_not_blank_grid(client_as, dish_pool):
    client, alice = client_as(username="alice")
    dishes = dish_pool(alice, count=3)
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )
    result = generate_plan(alice, profile, seed=1, days=3, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=3)
    for dish in dishes:
        dish.delete()

    client.post(f"/planner/plans/{plan.pk}/regenerate/")
    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()

    assert 'data-testid="empty-pool"' in body


def test_delete_plan_owner_only(client_as, plan_with_ingredients):
    client, alice = client_as(username="alice")
    plan = plan_with_ingredients(alice)
    client.post(f"/planner/plans/{plan.pk}/shopping/generate/")
    plan.refresh_from_db()
    list_id = plan.shopping_list_id
    assert list_id is not None
    entry_ids = list(plan.entries.values_list("pk", flat=True))

    response = client.post(f"/planner/plans/{plan.pk}/delete/")

    assert response.status_code == 302
    assert not MealPlan.objects.filter(pk=plan.pk).exists()
    assert not MealPlanEntry.objects.filter(pk__in=entry_ids).exists()
    assert List.objects.filter(pk=list_id).exists()  # the generated list survives (D44)


def test_delete_plan_forbidden_for_sharee(client_as, saved_plan, user_factory):
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)
    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    carol = user_factory(username="carol")
    plan.shared_with.add(carol)

    carol_client = Client()
    carol_client.force_login(carol)

    assert carol_client.get(f"/planner/plans/{plan.pk}/delete/").status_code == 403
    assert carol_client.post(f"/planner/plans/{plan.pk}/delete/").status_code == 403
    assert MealPlan.objects.filter(pk=plan.pk).exists()


def test_bulk_delete_plans(client_as, saved_plan, user_factory):
    client, alice = client_as(username="alice")
    p1 = saved_plan(alice, days=1)
    p2 = saved_plan(alice, days=1)
    bob = user_factory(username="bob")
    pb = MealPlan.objects.create(owner=bob, name="Bob", start_date=_START, days=1, seed=1)
    ids = [p1.pk, p2.pk, pb.pk]

    # unconfirmed → a confirm step, nothing removed
    confirm = client.post("/planner/plans/delete/", {"ids": ids})
    assert confirm.status_code == 200
    assert MealPlan.objects.filter(pk__in=ids).count() == 3

    done = client.post("/planner/plans/delete/", {"ids": ids, "confirm": "1"})
    assert done.status_code == 302
    assert not MealPlan.objects.filter(pk__in=[p1.pk, p2.pk]).exists()
    assert MealPlan.objects.filter(pk=pb.pk).exists()  # another user's id ignored, not an error


def test_share_plan_grants_read_only_access(client_as, saved_plan, user_factory):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=2)
    carol = user_factory(username="carol")

    client.post(f"/planner/plans/{plan.pk}/share/", {"visibility": "SHARED", "users": [carol.pk]})
    plan.refresh_from_db()
    assert carol in plan.shared_with.all()

    carol_client = Client()
    carol_client.force_login(carol)
    entry = plan.entries.first()

    assert carol_client.get(f"/planner/plans/{plan.pk}/").status_code == 200
    assert (
        carol_client.post(f"/planner/plans/{plan.pk}/entries/{entry.pk}/lock/").status_code == 403
    )
    assert (
        carol_client.post(f"/planner/plans/{plan.pk}/entries/{entry.pk}/reroll/").status_code == 403
    )
    assert (
        carol_client.post(
            f"/planner/plans/{plan.pk}/entries/{entry.pk}/swap/", {"dish": ""}
        ).status_code
        == 403
    )
    assert carol_client.post(f"/planner/plans/{plan.pk}/regenerate/").status_code == 403
    assert carol_client.get(f"/planner/plans/{plan.pk}/days/?days=1").status_code == 403
    assert carol_client.get(f"/planner/plans/{plan.pk}/shopping/preview/").status_code == 403
    assert carol_client.post(f"/planner/plans/{plan.pk}/shopping/generate/").status_code == 403


def test_unshare_plan_revokes_access(client_as, saved_plan, user_factory):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    carol = user_factory(username="carol")
    client.post(f"/planner/plans/{plan.pk}/share/", {"visibility": "SHARED", "users": [carol.pk]})

    carol_client = Client()
    carol_client.force_login(carol)
    assert carol_client.get(f"/planner/plans/{plan.pk}/").status_code == 200

    client.post(f"/planner/plans/{plan.pk}/unshare/", {"users": [carol.pk]})

    assert carol_client.get(f"/planner/plans/{plan.pk}/").status_code == 404


def test_share_modal_forbidden_for_sharee(client_as, saved_plan, user_factory):
    """The share modal is owner-only, like ``PlanDeleteView`` — a read-only sharee cannot
    open it even though any submit would 403 anyway (F2; design.md, "Share / unshare are
    owner-only")."""
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    carol = user_factory(username="carol")
    plan.shared_with.add(carol)

    carol_client = Client()
    carol_client.force_login(carol)

    assert carol_client.get(f"/planner/plans/{plan.pk}/share/modal/").status_code == 403


def test_reroll_empty_slot_that_stays_empty_shows_no_misleading_message(client_as):
    """Deliberately re-rolling an already-empty slot that stays empty is not a failure — it
    must not surface "Nothing changed — no other dish fits this slot." (F3)."""
    client, alice = client_as(username="alice")
    profile = MealPlanProfile.objects.create(
        owner=alice,
        name="P",
        source_scope="MINE",
        slots=["DINNER"],
        no_repeat_days=0,
        dish_template="ONE_POT",
    )
    result = generate_plan(alice, profile, seed=1, days=1, slots=["DINNER"])
    plan = save_plan(alice, result, profile=profile, start_date=_START, days=1)
    entry = plan.entries.get()
    assert entry.dish_id is None  # empty pool → unfilled slot

    response = client.post(
        f"/planner/plans/{plan.pk}/entries/{entry.pk}/reroll/", HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    assert "nothing changed" not in response.content.decode().lower()
    entry.refresh_from_db()
    assert entry.dish_id is None


def test_plan_card_links_to_plan(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)

    body = client.get("/planner/").content.decode()

    assert f'class="card-link" href="{plan.get_absolute_url()}"' in body


def test_plan_detail_renders_action_bar(client_as, saved_plan):
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)

    body = client.get(f"/planner/plans/{plan.pk}/").content.decode()

    assert "plan-actions" in body
    for label in ("Re-roll unlocked slots", "Shopping list", "Share", "Delete plan"):
        assert label in body


def test_profile_form_tag_limits_widget_roundtrips(client_as, make_tag):
    client, alice = client_as(username="alice")
    make_tag("chicken")
    make_tag("beef")

    response = client.post(
        "/planner/profiles/new/",
        {
            **_BASE_PROFILE_POST,
            "name": "TL",
            "tag_limits_tag": ["chicken", "beef"],
            "tag_limits_max": ["1", "2"],
        },
    )
    assert response.status_code == 302
    profile = MealPlanProfile.objects.get(name="TL")
    assert profile.tag_limits == {"chicken": 1, "beef": 2}

    body = client.get(f"/planner/profiles/{profile.pk}/").content.decode()
    assert '<option value="chicken" selected>' in body
    assert '<option value="beef" selected>' in body
    assert 'name="tag_limits_max" min="0" value="1"' in body
    assert 'name="tag_limits_max" min="0" value="2"' in body


def test_profile_form_rebound_with_saved_tag_limits_is_unchanged(client_as, make_tag):
    """Re-binding the form with its own saved ``{tag: int}`` value must not report the field
    as changed — ``TagLimitsField.has_changed`` compares ints, not int-vs-str (08.16)."""
    from django.http import QueryDict

    from planner.views import MealPlanProfileForm

    client, alice = client_as(username="alice")
    make_tag("chicken")
    profile = MealPlanProfile.objects.create(
        owner=alice, name="TL", slots=["DINNER"], tag_limits={"chicken": 1}
    )

    data = QueryDict(mutable=True)
    data.update(
        {
            "name": "TL",
            "days": str(profile.days),
            "dish_template": profile.dish_template,
            "source_scope": profile.source_scope,
            "no_repeat_days": str(profile.no_repeat_days),
            "favorites_bias": "1.5",
        }
    )
    data.setlist("slots", ["DINNER"])
    data.setlist("tag_limits_tag", ["chicken"])
    data.setlist("tag_limits_max", ["1"])

    form = MealPlanProfileForm(data=data, instance=profile, user=alice)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["tag_limits"] == {"chicken": 1}
    assert "tag_limits" not in form.changed_data


def test_profile_form_excluded_ingredients_render_as_checkboxes(client_as, make_ingredient):
    client, alice = client_as(username="alice")
    make_ingredient("Peanuts", owner=alice)

    body = client.get("/planner/profiles/new/").content.decode()

    assert 'type="checkbox" name="excluded_ingredients"' in body
    assert "Peanuts" in body


# =====================================================================================
# Dev-test rework round 2 (2026-09-07) — subtask 08.18
# =====================================================================================


def test_selectable_plan_card_renders_checkbox_and_link(client_as, saved_plan):
    """B1 — the bulk-delete card keeps both its select checkbox and the whole-card link, laid
    out with the checkbox in its own gutter so a future refactor cannot silently drop either.
    """
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)

    body = client.get("/planner/").content.decode()

    assert 'class="card card-selectable"' in body
    assert f'<input type="checkbox" name="ids" value="{plan.pk}">' in body
    assert f'class="card-link" href="{plan.get_absolute_url()}"' in body
    assert 'class="card-selectable-body"' in body


def test_profile_form_exclusion_lists_are_filterable(client_as, make_ingredient, make_tag):
    """B2 — both exclusion checkbox groups render the ``data-checklist`` container the
    client-side filter binds to (the JS itself is not exercised; the markup contract is)."""
    client, alice = client_as(username="alice")
    make_ingredient("Peanuts", owner=alice)
    make_tag("chicken")

    body = client.get("/planner/profiles/new/").content.decode()

    assert 'data-checklist="excluded_tags"' in body
    assert 'data-checklist="excluded_ingredients"' in body


def _tag_limits_widget(body: str) -> str:
    """The tag-limits widget markup, minus the ``<template>`` row the "Add row" script clones."""
    return body.split("data-tag-limits>", 1)[1].split("<template", 1)[0]


def test_tag_limits_widget_defaults_to_three_rows(client_as):
    """B3 — an unbound create form renders exactly three tag-limit rows (down from five)."""
    client, alice = client_as(username="alice")

    body = client.get("/planner/profiles/new/").content.decode()

    assert _tag_limits_widget(body).count('class="tag-limit-row"') == 3


def test_tag_limits_widget_render_includes_remove_control(client_as, make_tag):
    """B3 — every row carries the ``data-tag-limits-remove`` hook (hidden until JS reveals it)."""
    client, alice = client_as(username="alice")
    make_tag("chicken")

    widget = _tag_limits_widget(client.get("/planner/profiles/new/").content.decode())

    assert widget.count("data-tag-limits-remove") == 3


def test_tag_limits_fewer_rows_than_default_still_saves(client_as, make_tag):
    """B3 — removing rows needs no server change: one populated row plus one blank still saves
    a clean ``{tag: n}`` (``value_from_datadict`` tolerates a short / blank set)."""
    client, alice = client_as(username="alice")
    make_tag("chicken")

    response = client.post(
        "/planner/profiles/new/",
        {
            **_BASE_PROFILE_POST,
            "name": "Short",
            "tag_limits_tag": ["chicken", ""],
            "tag_limits_max": ["2", ""],
        },
    )

    assert response.status_code == 302
    assert MealPlanProfile.objects.get(name="Short").tag_limits == {"chicken": 2}


def test_rename_plan_owner_only(client_as, saved_plan, user_factory):
    """B4 — the owner renames a plan and the new name persists and renders; a read-only sharee
    cannot reach the rename endpoint (GET or POST → 403) and the name is unchanged."""
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)

    response = client.post(f"/planner/plans/{plan.pk}/rename/", {"name": "Week of roasts"})
    assert response.status_code == 302
    plan.refresh_from_db()
    assert plan.name == "Week of roasts"
    assert "Week of roasts" in client.get(plan.get_absolute_url()).content.decode()

    plan.visibility = "SHARED"
    plan.save(update_fields=["visibility"])
    carol = user_factory(username="carol")
    plan.shared_with.add(carol)
    carol_client = Client()
    carol_client.force_login(carol)

    rename_url = f"/planner/plans/{plan.pk}/rename/"
    assert carol_client.get(rename_url).status_code == 403
    assert carol_client.post(rename_url, {"name": "hijack"}).status_code == 403
    plan.refresh_from_db()
    assert plan.name == "Week of roasts"


# --- shared plans on the planner index + ownership badges (08.20 B2 / B3) -------------


def test_shared_plan_appears_in_sharees_planner_index(client_as, saved_plan, user_factory):
    """B2 — a plan shared hamon→avi shows in the sharee's ``/planner/`` under "Shared with
    you", with no select checkbox and no bulk-delete button in that section."""
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    carol = user_factory(username="carol")
    share(plan, actor=alice, users=[carol])

    carol_client = Client()
    carol_client.force_login(carol)
    body = carol_client.get("/planner/").content.decode()

    assert "Shared with you" in body
    assert f'href="{plan.get_absolute_url()}"' in body
    shared_section = body.split("Shared with you", 1)[1]
    assert 'name="ids"' not in shared_section
    assert "Delete selected" not in shared_section


def test_owner_still_sees_own_plans_with_bulk_delete(client_as, saved_plan):
    """Regression guard on the owner path (B2)."""
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)

    body = client.get("/planner/").content.decode()

    assert "Your plans" in body
    assert f'name="ids" value="{plan.pk}"' in body
    assert "Delete selected" in body
    assert "Shared with you" not in body


def test_invisible_plan_appears_in_neither_section(client_as, saved_plan, user_factory):
    """A private plan owned by someone else is in neither "Your plans" nor "Shared with
    you" (B2)."""
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    bob = user_factory(username="bob")

    bob_client = Client()
    bob_client.force_login(bob)
    body = bob_client.get("/planner/").content.decode()

    assert f'href="{plan.get_absolute_url()}"' not in body
    assert "Shared with you" not in body


def test_planner_index_shows_ownership_badges(client_as, saved_plan, user_factory):
    """B3 — the planner index badges an owned plan "Mine", a shared one "Shared with me",
    a public one "Public"."""
    client, alice = client_as(username="alice")
    mine = saved_plan(alice, days=1)
    shared_src = saved_plan(alice, days=1)
    public = saved_plan(alice, days=1)
    carol = user_factory(username="carol")
    share(shared_src, actor=alice, users=[carol])
    public.visibility = "PUBLIC"
    public.save(update_fields=["visibility"])

    own_body = client.get("/planner/").content.decode()
    assert "badge-mine" in own_body
    assert f'href="{mine.get_absolute_url()}"' in own_body

    carol_client = Client()
    carol_client.force_login(carol)
    carol_body = carol_client.get("/planner/").content.decode()
    assert "Shared with me" in carol_body
    assert "Public" in carol_body


def test_plan_detail_shows_ownership_badge_for_sharee(client_as, saved_plan, user_factory):
    """B3 — the badge is wired into ``plan_detail.html`` near the heading."""
    _client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    carol = user_factory(username="carol")
    share(plan, actor=alice, users=[carol])

    carol_client = Client()
    carol_client.force_login(carol)
    body = carol_client.get(f"/planner/plans/{plan.pk}/").content.decode()

    assert "Shared with me" in body


def test_rename_plan_blank_name(client_as, saved_plan):
    """B4 — renaming to blank is allowed (matches the generate flow): the plan then shows as
    "Untitled plan" on the index, not the old name."""
    client, alice = client_as(username="alice")
    plan = saved_plan(alice, days=1)
    client.post(f"/planner/plans/{plan.pk}/rename/", {"name": "Temporary"})

    response = client.post(f"/planner/plans/{plan.pk}/rename/", {"name": "   "})

    assert response.status_code == 302
    plan.refresh_from_db()
    assert plan.name == ""
    body = client.get("/planner/").content.decode()
    assert "Untitled plan" in body
    assert "Temporary" not in body
