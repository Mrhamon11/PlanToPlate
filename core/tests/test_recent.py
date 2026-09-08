"""``core.services.recent`` — the recently-viewed telemetry (``Plan/12-Home-Dashboard/
test-plan.md``, "Recently viewed").

The security cases (``test_recent_excludes_now_invisible_object``,
``test_recent_excludes_deleted_object``, ``test_recent_is_per_user``) matter most: a
``RecentView`` row records only that the user *once* could see an object, so every read
re-resolves it through ``.visible_to`` and never renders from the stored row.
"""

from __future__ import annotations

import pytest

from core.models import RecentView, Visibility
from core.services import recent
from core.services.recent import RECENT_VIEW_LIMIT, recent_for, record_view

pytestmark = pytest.mark.django_db


def test_record_view_creates_one_row(alice, make_recipe):
    recipe = make_recipe(owner=alice)

    record_view(alice, recipe)

    row = RecentView.objects.get()
    assert row.user_id == alice.id
    assert row.object_id == recipe.id
    assert row.content_object == recipe


def test_viewing_twice_updates_not_appends(alice, make_recipe):
    """One row, later ``viewed_at`` — the append-only failure mode this model exists to avoid."""
    recipe = make_recipe(owner=alice)

    record_view(alice, recipe)
    first = RecentView.objects.get().viewed_at

    record_view(alice, recipe)

    rows = RecentView.objects.all()
    assert len(rows) == 1
    assert rows[0].viewed_at >= first


def test_recent_ordered_newest_first(alice, make_recipe, make_dish):
    older = make_recipe("Older", owner=alice)
    newer = make_dish("Newer", owner=alice)

    record_view(alice, older)
    record_view(alice, newer)

    assert recent_for(alice) == [newer, older]


def test_recent_capped_at_limit(alice, make_recipe):
    recipes = [make_recipe(f"R{n}", owner=alice) for n in range(RECENT_VIEW_LIMIT + 10)]

    for recipe in recipes:
        record_view(alice, recipe)

    assert RecentView.objects.filter(user=alice).count() == RECENT_VIEW_LIMIT
    # The oldest ten were pruned; the newest survives.
    surviving_ids = set(RecentView.objects.filter(user=alice).values_list("object_id", flat=True))
    assert recipes[0].id not in surviving_ids
    assert recipes[-1].id in surviving_ids


def test_record_view_swallows_write_failure(alice, make_recipe, monkeypatch):
    """A raising ``update_or_create`` does not propagate — the detail page still renders."""
    recipe = make_recipe(owner=alice)

    def boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(RecentView.objects, "update_or_create", boom)

    record_view(alice, recipe)  # must not raise

    assert RecentView.objects.count() == 0


def test_recent_excludes_now_invisible_object(alice, bob, make_recipe, share_with):
    """The security case: record a view of a shared recipe, revoke the share, and it is gone
    from ``recent_for`` — not rendered from the stored row.
    """
    recipe = make_recipe("Bob's", owner=bob)
    share_with(recipe, alice)

    record_view(alice, recipe)
    assert recent_for(alice) == [recipe]

    recipe.shared_with.remove(alice)

    assert recent_for(alice) == []
    # The row is left in the table — pruned on write, skipped on read.
    assert RecentView.objects.filter(user=alice).count() == 1


def test_recent_excludes_deleted_object(alice, make_recipe, make_dish):
    recipe = make_recipe(owner=alice)
    dish = make_dish(owner=alice)
    record_view(alice, recipe)
    record_view(alice, dish)

    recipe.delete()

    assert recent_for(alice) == [dish]


def test_recent_is_per_user(alice, bob, make_recipe):
    """Bob's history never appears in Alice's."""
    recipe = make_recipe("Alice's", owner=alice)
    share_recipe = make_recipe("Shared", owner=alice)
    share_recipe.visibility = Visibility.PUBLIC
    share_recipe.save(update_fields=["visibility"])

    record_view(bob, share_recipe)
    record_view(alice, recipe)

    assert recent_for(alice) == [recipe]
    assert recent_for(bob) == [share_recipe]


def test_recent_resolves_one_query_per_content_type(
    alice, make_recipe, make_dish, make_book, django_assert_num_queries
):
    """Generic references resolve with one ``visible_to`` query per content type, not per row."""
    for n in range(3):
        record_view(alice, make_recipe(f"R{n}", owner=alice))
        record_view(alice, make_dish(f"D{n}", owner=alice))
        record_view(alice, make_book(f"B{n}", owner=alice))

    # 1 query for the rows + 1 visible_to per content type (recipe / dish / book) = 4.
    with django_assert_num_queries(4):
        results = recent.recent_for(alice, limit=99)

    assert len(results) == 9
