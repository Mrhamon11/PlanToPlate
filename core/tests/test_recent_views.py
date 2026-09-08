"""View recording — the ``RecordsRecentView`` mixin on the recipe / dish / book **detail**
views (``Plan/12-Home-Dashboard/test-plan.md``, "View recording").

Detail pages record; list pages, HTMX fragment refreshes and the print page do not.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from core.models import RecentView

pytestmark = pytest.mark.django_db


def _rows(user):
    return RecentView.objects.filter(user=user)


def test_recipe_detail_records_view(client, alice, make_recipe):
    recipe = make_recipe(owner=alice)
    client.force_login(alice)

    assert client.get(reverse("recipes:recipe-detail", args=[recipe.pk])).status_code == 200

    assert _rows(alice).get().object_id == recipe.pk


def test_dish_detail_records_view(client, alice, dish_with_component):
    dish = dish_with_component(owner=alice)
    client.force_login(alice)

    assert client.get(reverse("meals:dish-detail", args=[dish.pk])).status_code == 200

    assert _rows(alice).get().object_id == dish.pk


def test_book_detail_records_view(client, alice, make_book):
    book = make_book(owner=alice)
    client.force_login(alice)

    assert client.get(reverse("meals:book-detail", args=[book.pk])).status_code == 200

    assert _rows(alice).get().object_id == book.pk


def test_list_page_does_not_record(client, alice, make_recipe):
    make_recipe(owner=alice)
    client.force_login(alice)

    assert client.get(reverse("recipes:recipe-list")).status_code == 200

    assert not _rows(alice).exists()


def test_htmx_fragment_does_not_record(client, alice, make_book):
    """A fragment refresh must not create or bump a row."""
    book = make_book(owner=alice)
    client.force_login(alice)
    url = reverse("meals:book-detail", args=[book.pk])

    client.get(url)  # a real visit records
    first_seen = _rows(alice).get().viewed_at

    client.get(url, HTTP_HX_REQUEST="true")  # a fragment refresh must not

    row = _rows(alice).get()
    assert row.viewed_at == first_seen


def test_print_view_does_not_record(client, alice, make_recipe):
    recipe = make_recipe(owner=alice)
    client.force_login(alice)

    assert client.get(reverse("recipes:recipe-print", args=[recipe.pk])).status_code == 200

    assert not _rows(alice).exists()
