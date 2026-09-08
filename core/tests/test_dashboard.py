"""``core.services.dashboard.build_dashboard`` — the home dashboard read model
(``Plan/12-Home-Dashboard/test-plan.md``, "Dashboard service").

Covers the panel logic and the query budget (``test_dashboard_query_count``, 12.15). Template
rendering lives in ``test_templates.py``, the REST rendering in ``test_dashboard_api.py``.

Every panel query goes through ``.visible_to(user)`` — the security rows below
(``test_favourites_exclude_unshared_object``, ``test_shared_with_you_hides_share_audience``)
are the ones that matter most.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import resolve
from django.utils import timezone

from core.services.dashboard import EmptyPanel, build_dashboard
from core.services.recent import record_view
from planner.models import MealSlot

pytestmark = pytest.mark.django_db


# --- this week ---------------------------------------------------------------------------


def test_this_week_shows_active_plan(alice, make_plan, add_entry, dish_with_component):
    today = timezone.localdate()
    plan = make_plan(owner=alice, start_date=today - datetime.timedelta(days=1), days=7)
    dinner = dish_with_component("Tonight", owner=alice)
    add_entry(plan, day_index=0, slot=MealSlot.DINNER, dish=dish_with_component("Yesterday"))
    add_entry(plan, day_index=1, slot=MealSlot.DINNER, dish=dinner)

    panel = build_dashboard(alice).this_week

    assert panel is not None
    assert panel.plan_id == plan.pk
    # Today is first and flagged; yesterday's day is not shown.
    assert panel.days[0].is_today is True
    assert panel.days[0].date == today
    assert panel.days[0].day_index == 1
    assert panel.days[0].slots[0].dish_name == "Tonight"


def test_this_week_ignores_ended_plan(alice, make_plan, add_entry, dish_with_component):
    today = timezone.localdate()
    make_plan(
        owner=alice,
        start_date=today - datetime.timedelta(days=10),
        days=3,  # ended a week ago
    )

    panel = build_dashboard(alice).this_week

    # Not the ended plan, and not ``None`` — the flagship panels always render, as a CTA
    # into the planner when there is no active week (``design.md`` panel table).
    assert isinstance(panel, EmptyPanel)
    assert resolve(panel.forward_url).view_name == "planner:plan-generate"


def test_this_week_only_shows_own_plan(alice, bob, make_plan, share_with):
    today = timezone.localdate()
    plan = make_plan(owner=bob, start_date=today - datetime.timedelta(days=1), days=7)
    share_with(plan, alice)

    panel = build_dashboard(alice).this_week

    assert isinstance(panel, EmptyPanel)
    assert resolve(panel.forward_url).view_name == "planner:plan-generate"


# --- shopping ---------------------------------------------------------------------------


def test_shopping_panel_uses_default_list(alice, make_list, add_ingredient, make_ingredient):
    from lists.models import ListItem, ListKind

    default = make_list(
        "Groceries", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True
    )
    other = make_list("Party", owner=alice, kind=ListKind.SHOPPING)
    ListItem.objects.create(list=default, position=0, text="milk")
    ListItem.objects.create(list=other, position=0, text="balloons")

    panel = build_dashboard(alice).shopping

    assert panel is not None
    assert panel.list_id == default.pk
    assert panel.name == "Groceries"
    assert other.pk != panel.list_id


def test_shopping_panel_progress_counts(alice, make_list):
    from lists.models import ListItem, ListKind

    lst = make_list("Groceries", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True)
    ListItem.objects.create(list=lst, position=0, text="milk", is_checked=True)
    ListItem.objects.create(list=lst, position=1, text="eggs")
    ListItem.objects.create(list=lst, position=2, text="bread")

    panel = build_dashboard(alice).shopping

    assert (panel.checked, panel.total) == (1, 3)


# --- favourites -------------------------------------------------------------------------


def test_favourites_exclude_unshared_object(alice, bob, make_recipe, share_with, set_favourite):
    recipe = make_recipe("Bob's best", owner=bob)
    share_with(recipe, alice)
    set_favourite(alice, recipe)

    assert [c.name for c in build_dashboard(alice).favourites] == ["Bob's best"]

    recipe.shared_with.remove(alice)

    assert build_dashboard(alice).favourites == []


def test_favourites_include_own_recipes_and_dishes(
    alice, make_recipe, dish_with_component, set_favourite
):
    recipe = make_recipe("Fav recipe", owner=alice)
    dish = dish_with_component("Fav dish", owner=alice)
    set_favourite(alice, recipe)
    set_favourite(alice, dish)

    names = {c.name for c in build_dashboard(alice).favourites}
    assert names == {"Fav recipe", "Fav dish"}


def test_favourites_do_not_starve_dishes(alice, make_recipe, dish_with_component, set_favourite):
    """A user with more favourite recipes than the panel can hold must still see their
    favourite dishes — the panel reserves slots for each kind rather than concatenating and
    slicing (N2, task 12 reviewer).
    """
    from core.services.dashboard import FAVOURITES_LIMIT

    for i in range(FAVOURITES_LIMIT + 4):
        set_favourite(alice, make_recipe(f"Recipe {i:02d}", owner=alice))
    for i in range(3):
        set_favourite(alice, dish_with_component(f"Dish {i}", owner=alice))

    cards = build_dashboard(alice).favourites
    kinds = [c.kind for c in cards]

    assert len(cards) == FAVOURITES_LIMIT
    assert "Recipe" in kinds
    assert kinds.count("Dish") == 3


# --- shared with you ---------------------------------------------------------------------


def test_shared_with_you_lists_others_objects(alice, bob, make_recipe, share_with):
    theirs = make_recipe("Theirs", owner=bob)
    share_with(theirs, alice)
    make_recipe("Mine", owner=alice)

    cards = build_dashboard(alice).shared_with_you

    assert [c.name for c in cards] == ["Theirs"]
    assert cards[0].owner_username == "bob"


def test_shared_with_you_hides_share_audience(alice, bob, carol, make_recipe, share_with):
    """D35 — the owner's username only, never the rest of ``shared_with``."""
    recipe = make_recipe("Group recipe", owner=bob)
    share_with(recipe, alice)
    recipe.shared_with.add(carol)

    cards = build_dashboard(alice).shared_with_you

    assert cards[0].owner_username == "bob"
    assert not hasattr(cards[0], "shared_with")
    assert "carol" not in repr(cards)


# --- public from others ----------------------------------------------------------------


def _make_public(obj):
    from core.models import Visibility

    obj.visibility = Visibility.PUBLIC
    obj.save(update_fields=["visibility"])
    return obj


def test_public_from_others_lists_public_not_shared(alice, bob, make_recipe):
    """A PUBLIC object the viewer was never shared on shows up in "Public from others" and
    not in "Shared with you".
    """
    _make_public(make_recipe("Bob's public", owner=bob))

    ctx = build_dashboard(alice)

    assert [c.name for c in ctx.public_from_others] == ["Bob's public"]
    assert ctx.public_from_others[0].owner_username == "bob"
    assert ctx.shared_with_you == []


def test_shared_row_absent_from_public_panel(alice, bob, make_recipe, share_with):
    """An explicitly-shared object appears only in "Shared with you"."""
    share_with(make_recipe("Explicitly shared", owner=bob), alice)

    ctx = build_dashboard(alice)

    assert [c.name for c in ctx.shared_with_you] == ["Explicitly shared"]
    assert ctx.public_from_others == []


def test_shared_and_public_row_appears_only_in_shared(alice, bob, make_recipe, share_with):
    """A row that is both explicitly shared and PUBLIC belongs to "Shared with you" only —
    exactly one panel, never both.
    """
    recipe = share_with(make_recipe("Shared and public", owner=bob), alice)
    _make_public(recipe)

    ctx = build_dashboard(alice)

    assert [c.name for c in ctx.shared_with_you] == ["Shared and public"]
    assert ctx.public_from_others == []


def test_public_from_others_hides_share_audience(alice, bob, carol, make_recipe):
    """D35 — the new panel exposes the owner's username only, never the rest of
    ``shared_with``.
    """
    recipe = _make_public(make_recipe("Public group recipe", owner=bob))
    recipe.shared_with.add(carol)

    cards = build_dashboard(alice).public_from_others

    assert cards[0].owner_username == "bob"
    assert not hasattr(cards[0], "shared_with")
    assert "carol" not in repr(cards)


def test_public_from_others_excludes_own_and_system(alice, make_recipe):
    _make_public(make_recipe("My own public", owner=alice))

    assert build_dashboard(alice).public_from_others == []


# --- what should I make? -----------------------------------------------------------------


def test_suggestion_excludes_empty_dishes(alice, make_dish, dish_with_component):
    make_dish("Empty one", owner=alice)
    make_dish("Empty two", owner=alice)
    real = dish_with_component("Has a recipe", owner=alice)

    for _ in range(10):
        assert build_dashboard(alice).suggestion.name == real.name
    assert build_dashboard(alice).suggestion.url == real.get_absolute_url()


def test_suggestion_only_from_visible_dishes(alice, bob, dish_with_component):
    dish_with_component("Bob's private", owner=bob)

    assert build_dashboard(alice).suggestion is None

    mine = dish_with_component("Mine", owner=alice)
    for _ in range(10):
        assert build_dashboard(alice).suggestion.name == mine.name


# --- sections -------------------------------------------------------------------------


def test_section_counts_are_visibility_scoped(alice, bob, make_recipe):
    for n in range(3):
        make_recipe(f"Alice {n}", owner=alice)
    make_recipe("Bob's", owner=bob)

    def recipe_count(user):
        sections = {s.label: s.count for s in build_dashboard(user).sections}
        return sections["Recipes"]

    assert recipe_count(alice) == 3
    assert recipe_count(bob) == 1


def test_sections_always_present_for_new_user(carol):
    labels = [s.label for s in build_dashboard(carol).sections]
    assert labels == ["Recipes", "Dishes", "Books", "Lists", "Meal plans"]
    assert all(s.count == 0 for s in build_dashboard(carol).sections)


# --- empty state ---------------------------------------------------------------------


def test_empty_panels_are_absent(carol):
    """A brand-new user's context carries no *secondary* empty panels to render — the two
    flagship panels always carry a payload (an ``EmptyPanel`` CTA when there is nothing yet).
    """
    ctx = build_dashboard(carol)

    assert isinstance(ctx.this_week, EmptyPanel)
    assert isinstance(ctx.shopping, EmptyPanel)
    assert resolve(ctx.this_week.forward_url).view_name == "planner:plan-generate"
    assert resolve(ctx.shopping.forward_url).view_name == "lists:index"
    assert ctx.recently_viewed == []
    assert ctx.favourites == []
    assert ctx.shared_with_you == []
    assert ctx.public_from_others == []
    assert ctx.suggestion is None
    assert len(ctx.sections) == 5
    assert ctx.show_get_started is True


def test_flagship_ctas_for_user_with_content_but_no_plan_or_list(
    carol, make_recipe, dish_with_component
):
    """The common intermediate state: owns recipes/dishes, has not yet planned a week or made
    a shopping list. ``show_get_started`` does not fire (the account is not empty), so the two
    flagship CTAs are the only on-ramp into planning and shopping (blocking finding #1).
    """
    make_recipe("Carol's recipe", owner=carol)
    dish_with_component("Carol's dish", owner=carol)

    ctx = build_dashboard(carol)

    assert ctx.show_get_started is False
    assert isinstance(ctx.this_week, EmptyPanel)
    assert isinstance(ctx.shopping, EmptyPanel)
    assert resolve(ctx.this_week.forward_url).view_name == "planner:plan-generate"
    assert resolve(ctx.shopping.forward_url).view_name == "lists:index"


def test_get_started_hidden_when_user_owns_content_but_has_no_activity(carol, make_recipe):
    """Owning recipes is not being a brand-new user, even with no views/favourites/plan/list.
    The "add your first recipe" line is tied to an empty account, not an idle one.
    """
    make_recipe("Carol's first", owner=carol)

    ctx = build_dashboard(carol)

    assert ctx.recently_viewed == []
    assert ctx.favourites == []
    assert {s.label: s.count for s in ctx.sections}["Recipes"] == 1
    assert ctx.show_get_started is False


# --- query budget -------------------------------------------------------------------------


def test_dashboard_query_count(
    alice,
    bob,
    make_plan,
    add_entry,
    dish_with_component,
    make_recipe,
    make_book,
    make_list,
    make_ingredient,
    make_tag,
    share_with,
    set_favourite,
    django_assert_max_num_queries,
):
    """A user with data in **every** panel stays within a hard, bounded query count — this is
    the most-requested page in the app and it fans out across six models (``design.md``,
    "Query budget"). The bound only moves for a deliberate reason.
    """
    today = timezone.localdate()
    plan = make_plan(owner=alice, start_date=today - datetime.timedelta(days=1), days=7)
    add_entry(plan, day_index=1, slot=MealSlot.DINNER, dish=dish_with_component("D1", owner=alice))
    add_entry(plan, day_index=2, slot=MealSlot.DINNER, dish=dish_with_component("D2", owner=alice))

    from lists.models import ListItem, ListKind

    shopping = make_list(
        "Groceries", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True
    )
    produce = make_tag("Produce")
    for i in range(6):
        ingredient = make_ingredient(f"Ing{i}", owner=alice)
        ingredient.tags.add(produce)
        ListItem.objects.create(list=shopping, position=i, ingredient=ingredient, quantity=1)

    for i in range(3):
        recipe = make_recipe(f"R{i}", owner=alice)
        record_view(alice, recipe)
        set_favourite(alice, recipe)
    favourite_dish = dish_with_component("Fav dish", owner=alice)
    record_view(alice, favourite_dish)
    set_favourite(alice, favourite_dish)
    record_view(alice, make_book("My book", owner=alice))

    share_with(make_recipe("Shared recipe", owner=bob), alice)
    share_with(dish_with_component("Shared dish", owner=bob), alice)

    from core.models import Visibility

    public_recipe = make_recipe("Bob's public recipe", owner=bob)
    public_recipe.visibility = Visibility.PUBLIC
    public_recipe.save(update_fields=["visibility"])

    with django_assert_max_num_queries(26):
        ctx = build_dashboard(alice)

    # Every panel actually has something to say — otherwise the budget is measured against a
    # half-empty page.
    assert ctx.this_week is not None
    assert ctx.shopping is not None and ctx.shopping.groups
    assert ctx.recently_viewed and ctx.favourites and ctx.shared_with_you
    assert ctx.public_from_others
    assert ctx.suggestion is not None
