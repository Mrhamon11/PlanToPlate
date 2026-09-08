"""``GET /api/dashboard/`` — the read-only dashboard API (``Plan/12-Home-Dashboard/
test-plan.md``, "API").

The endpoint is a second *rendering* of ``core.services.dashboard.build_dashboard``, never a
second *implementation*: the parity test below is what keeps it that way. It must also never
become a way to read another user's history (``design.md``, "Security notes").
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from core.services.dashboard import build_dashboard
from planner.models import MealSlot

pytestmark = pytest.mark.django_db

URL = reverse("core_api:dashboard")


def test_dashboard_endpoint_requires_auth(client):
    assert client.get(URL).status_code in (401, 403)


def test_dashboard_endpoint_matches_service(
    client,
    alice,
    bob,
    make_plan,
    add_entry,
    dish_with_component,
    make_recipe,
    make_book,
    make_list,
    make_ingredient,
    gram,
    set_favourite,
    share_with,
):
    """Same panel content as the HTML page — one implementation, two renderings."""
    today = timezone.localdate()
    plan = make_plan(owner=alice, start_date=today - datetime.timedelta(days=1), days=7)
    add_entry(
        plan, day_index=1, slot=MealSlot.DINNER, dish=dish_with_component("Tonight", owner=alice)
    )
    from lists.models import ListItem, ListKind

    shopping = make_list(
        "Groceries", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True
    )
    ListItem.objects.create(list=shopping, position=0, text="milk", is_checked=True)
    ListItem.objects.create(list=shopping, position=1, text="eggs")
    ListItem.objects.create(
        list=shopping,
        position=2,
        ingredient=make_ingredient("Carrots", owner=alice),
        quantity="500",
        unit=gram,
    )

    favourite = make_recipe("Fav", owner=alice)
    set_favourite(alice, favourite)
    share_with(make_recipe("From bob", owner=bob), alice)
    make_book("Book", owner=alice)

    from core.models import Visibility

    public = make_recipe("Bob's public", owner=bob)
    public.visibility = Visibility.PUBLIC
    public.save(update_fields=["visibility"])

    client.force_login(alice)
    body = client.get(URL).json()

    expected = build_dashboard(alice)

    assert body["this_week"]["plan_id"] == expected.this_week.plan_id
    assert body["this_week"]["days"][0]["slots"][0]["dish_name"] == "Tonight"
    assert (body["shopping"]["checked"], body["shopping"]["total"]) == (
        expected.shopping.checked,
        expected.shopping.total,
    )
    # The ingredient-backed preview line serialises its resolved label, quantity and unit —
    # a regression in annotate_display wiring or the ``source=`` mappings would be caught.
    preview_items = [item for group in body["shopping"]["groups"] for item in group["items"]]
    carrots = next(item for item in preview_items if item["label"] == "Carrots")
    assert carrots["quantity"] == "500.000"
    assert carrots["unit"] == "g"
    assert [c["name"] for c in body["favourites"]] == [c.name for c in expected.favourites]
    assert body["shared_with_you"][0]["owner_username"] == "bob"
    assert [c["name"] for c in body["public_from_others"]] == [
        c.name for c in expected.public_from_others
    ]
    assert body["public_from_others"][0]["name"] == "Bob's public"
    assert body["public_from_others"][0]["owner_username"] == "bob"
    assert {s["label"]: s["count"] for s in body["sections"]} == {
        s.label: s.count for s in expected.sections
    }
    assert body["show_get_started"] is False


def test_dashboard_flagship_panels_carry_forward_url_when_empty(client, alice):
    """ "This week" / "Shopping" never serialise as ``null`` — with no active plan and no
    default list they carry only the forward URL for their CTA (blocking finding #1).
    """
    client.force_login(alice)
    body = client.get(URL).json()

    assert body["this_week"]["forward_url"] == reverse("planner:plan-generate")
    assert body["shopping"]["forward_url"] == reverse("lists:index")


def test_dashboard_endpoint_is_read_only(client, alice):
    client.force_login(alice)
    assert client.post(URL, {}).status_code == 405
    assert client.put(URL, {}).status_code == 405
    assert client.delete(URL).status_code == 405


def test_dashboard_never_exposes_another_users_history(client, alice, bob, make_recipe, share_with):
    """A ``RecentView`` row is private to its user — Bob's viewing history is never in Alice's
    dashboard, even for an object they can both see (``design.md``, "Security notes").
    """
    from core.services.recent import record_view

    shared = make_recipe("Shared thing", owner=alice)
    share_with(shared, bob)
    record_view(bob, shared)

    client.force_login(alice)
    body = client.get(URL).json()

    assert body["recently_viewed"] == []
