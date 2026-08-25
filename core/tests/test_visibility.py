"""Plan/03-Ownership-And-Sharing/test-plan.md, "The visibility matrix —
core/tests/test_visibility.py".

The single most important test file in the project (test-plan.md's own words): everything
built on top of ``OwnedQuerySet.visible_to()``/``editable_by()`` inherits whatever this file
proves or fails to prove.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser

from core.models import Visibility
from core.tests.models import DummyOwned

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "visibility,is_system,share_with_bob,viewer_name,expected_visible",
    [
        # PRIVATE: only the owner sees it.
        (Visibility.PRIVATE, False, False, "alice", True),
        (Visibility.PRIVATE, False, False, "bob", False),
        (Visibility.PRIVATE, False, False, "carol", False),
        # SHARED, bob explicitly granted: owner and grantee see it, carol does not.
        (Visibility.SHARED, False, True, "alice", True),
        (Visibility.SHARED, False, True, "bob", True),
        (Visibility.SHARED, False, True, "carol", False),
        # PUBLIC: everyone with an account sees it.
        (Visibility.PUBLIC, False, False, "alice", True),
        (Visibility.PUBLIC, False, False, "bob", True),
        (Visibility.PUBLIC, False, False, "carol", True),
        # System object: everyone sees it, regardless of visibility field.
        (Visibility.PRIVATE, True, False, "alice", True),
        (Visibility.PRIVATE, True, False, "bob", True),
        (Visibility.PRIVATE, True, False, "carol", True),
    ],
    ids=[
        "private-owner-visible",
        "private-shared-not-granted-hidden",
        "private-unrelated-hidden",
        "shared-owner-visible",
        "shared-grantee-visible",
        "shared-unrelated-hidden",
        "public-owner-visible",
        "public-other-visible",
        "public-unrelated-visible",
        "system-visible-to-anyone-1",
        "system-visible-to-anyone-2",
        "system-visible-to-anyone-3",
    ],
)
def test_visibility_matrix(
    alice, bob, carol, visibility, is_system, share_with_bob, viewer_name, expected_visible
):
    owner = None if is_system else alice
    obj = DummyOwned.objects.create(owner=owner, visibility=visibility, is_system=is_system)
    if share_with_bob:
        obj.shared_with.add(bob)

    viewer = {"alice": alice, "bob": bob, "carol": carol}[viewer_name]

    is_visible = DummyOwned.objects.visible_to(viewer).filter(pk=obj.pk).exists()
    assert is_visible is expected_visible


def test_anonymous_gets_empty_queryset(alice):
    """A missing @login_required must degrade to an empty list, never to a leak."""
    DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)

    result = DummyOwned.objects.visible_to(AnonymousUser())

    assert list(result) == []


def test_visible_to_is_distinct(alice, bob, carol, user_factory):
    """An object shared with three users must appear once, not once per grant.

    Without ``.distinct()``, combining the M2M ``shared_with`` condition via OR with the
    ``owner`` condition in one filter() call produces a duplicate output row per matching grant
    row — here, querying as the owner (who already matches via the ``owner`` clause alone)
    would come back three times, once per person the object is shared with.
    """
    dan = user_factory(username="dan")
    obj = DummyOwned.objects.create(owner=alice)
    obj.shared_with.add(bob, carol, dan)

    results = list(DummyOwned.objects.visible_to(alice).filter(pk=obj.pk))

    assert len(results) == 1


def test_editable_by_owner_only(alice, bob, carol):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)
    obj.shared_with.add(bob)

    assert DummyOwned.objects.editable_by(alice).filter(pk=obj.pk).exists() is True
    assert DummyOwned.objects.editable_by(bob).filter(pk=obj.pk).exists() is False
    assert DummyOwned.objects.editable_by(carol).filter(pk=obj.pk).exists() is False


def test_editable_by_excludes_system(admin):
    """Even a superuser cannot get a system object through ``editable_by`` — there is no
    ``is_superuser`` carve-out anywhere in ``OwnedQuerySet``, and this test pins that absence.

    The fixture object has ``owner=None``, so ``filter(owner=admin)`` alone already excludes it
    — the assertion above would stay green even if the ``is_system=False`` clause were deleted
    from ``editable_by``. The clause below pins that condition directly, since finding 4
    (03-Ownership-And-Sharing review) makes it genuinely load-bearing: a subclass missing the
    XOR constraint can carry a non-system row with a real owner *and* ``is_system`` left
    accidentally ``True``, which only the explicit clause — not the ``owner=`` filter — would
    exclude.

    Asserting ``"is_system"`` against ``str(qs.query)`` alone would not discriminate: that
    string always lists ``is_system`` among the selected columns regardless of whether the
    ``WHERE`` clause filters on it (03-Ownership-And-Sharing review, iteration-2 blocking
    finding 6). Splitting on ``" WHERE "`` first and checking only the clause portion does.
    """
    obj = DummyOwned.objects.create(owner=None, is_system=True)

    assert DummyOwned.objects.editable_by(admin).filter(pk=obj.pk).exists() is False
    where_clause = str(DummyOwned.objects.editable_by(admin).query).split(" WHERE ", 1)[1]
    assert "is_system" in where_clause


def test_editable_by_anonymous_returns_none():
    result = DummyOwned.objects.editable_by(AnonymousUser())

    assert list(result) == []


def test_visible_to_none_user_returns_none(alice):
    """``user=None`` (a service or management command with no request to hand over) must
    degrade to ``.none()`` the same way ``AnonymousUser`` does, rather than raising
    ``AttributeError`` on ``None.is_authenticated`` (03-Ownership-And-Sharing review,
    iteration-1 non-blocking finding 5).
    """
    DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)

    assert list(DummyOwned.objects.visible_to(None)) == []


def test_editable_by_none_user_returns_none(alice):
    DummyOwned.objects.create(owner=alice)

    assert list(DummyOwned.objects.editable_by(None)) == []


def test_visible_to_query_count(alice, django_assert_num_queries):
    """The filter must not degrade to N+1 on a list of 50 — it is one query regardless of how
    many rows come back.
    """
    for _ in range(50):
        DummyOwned.objects.create(owner=alice)

    with django_assert_num_queries(1):
        list(DummyOwned.objects.visible_to(alice))
