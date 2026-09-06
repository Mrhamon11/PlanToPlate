"""``get_or_create_default_shopping_list`` (``Plan/07-Lists-And-Shopping/test-plan.md``,
"Default list service").
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lists.models import List, ListKind
from lists.services import get_or_create_default_shopping_list

pytestmark = pytest.mark.django_db


def test_creates_when_missing(alice):
    lst = get_or_create_default_shopping_list(alice)
    assert lst.name == "Shopping List"
    assert lst.kind == ListKind.SHOPPING
    assert lst.is_default_shopping_list is True
    assert lst.owner == alice


def test_returns_existing(alice):
    first = get_or_create_default_shopping_list(alice)
    second = get_or_create_default_shopping_list(alice)
    assert first.pk == second.pk
    assert List.objects.filter(owner=alice, is_default_shopping_list=True).count() == 1


def test_race_safe(alice):
    """Two concurrent calls yield one list, not two: the losing creator's insert hits the
    ``lists_list_one_default_shopping_per_owner`` partial unique constraint, and the service
    catches the ``IntegrityError`` and re-reads rather than raising or returning a duplicate.
    """
    winner = List.objects.create(
        owner=alice,
        name="Shopping List",
        kind=ListKind.SHOPPING,
        is_default_shopping_list=True,
    )

    # Force the initial existence check to miss, as it would for the request that lost the race
    # (it read before the winner committed). The create that follows then really does collide.
    with patch("lists.services.List.objects.filter") as mock_filter:
        mock_filter.return_value.first.return_value = None
        result = get_or_create_default_shopping_list(alice)

    assert result.pk == winner.pk
    assert List.objects.filter(owner=alice, is_default_shopping_list=True).count() == 1
