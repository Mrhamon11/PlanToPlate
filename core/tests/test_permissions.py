"""Plan/03-Ownership-And-Sharing/test-plan.md, "Permissions — core/tests/test_permissions.py".

These are unit tests against the permission classes directly, exercised with a bare DRF
``Request`` (built via ``APIRequestFactory``) and the throwaway ``DummyOwned`` model — there is
no ``OwnedViewSetMixin``/live API route yet (that lands in 03.8), so the queryset-dependent
half of the design's guarantee cannot be exercised here.

**Deferred to 03.8**, when real routes exist: ``test_unrelated_user_gets_404_not_403``. That
behaviour comes from DRF's ``get_object()`` calling ``get_queryset().visible_to(user)`` *before*
any permission class runs — an invisible object never reaches ``has_object_permission`` at all,
so it cannot be demonstrated by calling these permission classes directly. It requires a live
viewset and is listed in test-plan.md's IDOR matrix (``test_idor.py``), not here.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core.models import Visibility
from core.permissions import CanCopy, IsOwner, IsOwnerOrReadOnly
from core.tests.models import DummyOwned

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


def _request(method: str, user) -> Request:
    django_request = getattr(_factory, method.lower())("/")
    request = Request(django_request)
    request.user = user
    return request


# --- IsOwnerOrReadOnly -------------------------------------------------------------------


def test_owner_can_write(alice):
    obj = DummyOwned.objects.create(owner=alice)

    assert IsOwnerOrReadOnly().has_object_permission(_request("PUT", alice), None, obj) is True


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_shared_user_cannot_write(alice, bob, method):
    """PUT/PATCH/DELETE must be denied on an object merely shared *to* the requester."""
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    assert IsOwnerOrReadOnly().has_object_permission(_request(method, bob), None, obj) is False


def test_shared_user_can_read(alice, bob):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    assert IsOwnerOrReadOnly().has_object_permission(_request("GET", bob), None, obj) is True


def test_unrelated_user_cannot_read_private_object_via_permission_class_alone(alice, carol):
    """The safe-method branch must consult visibility itself, not allow every safe method
    unconditionally — the secondary defence design.md requires (blocking finding 2). Exercised
    directly against the permission class, without relying on ``get_queryset()`` having already
    filtered anything out, since that queryset filter is exactly the thing this class exists to
    back up if it is ever missing.
    """
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PRIVATE)

    result = IsOwnerOrReadOnly().has_object_permission(_request("GET", carol), None, obj)

    assert result is False
    # And the queryset genuinely agrees it is invisible, so this isn't testing a fact that
    # doesn't hold anywhere else.
    assert DummyOwned.objects.visible_to(carol).filter(pk=obj.pk).exists() is False


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_anonymous_denied_on_ownerless_object(method):
    """A permission class must fail closed on its own: ``AnonymousUser().id`` and an ownerless
    row's ``owner_id`` can both be ``None``, which must never grant access via ``None == None``
    (blocking finding 3).
    """
    obj = DummyOwned(owner_id=None, is_system=False)

    result = IsOwnerOrReadOnly().has_object_permission(_request(method, AnonymousUser()), None, obj)

    assert result is False


def test_public_object_not_writable_by_others(alice, carol):
    """Public means readable, never writable, by anyone but the owner."""
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)

    assert IsOwnerOrReadOnly().has_object_permission(_request("GET", carol), None, obj) is True
    assert IsOwnerOrReadOnly().has_object_permission(_request("PUT", carol), None, obj) is False


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_system_object_not_writable_by_anyone(admin, method):
    """Including staff/superusers, through the API — a system object is only ever writable via
    fixtures and the admin site, never through this permission class.
    """
    obj = DummyOwned.objects.create(owner=None, is_system=True)

    result = IsOwnerOrReadOnly().has_object_permission(_request(method, admin), None, obj)

    if method == "GET":
        assert result is True
    else:
        assert result is False


# --- IsOwner -------------------------------------------------------------------------------


def test_is_owner_allows_owner(alice):
    obj = DummyOwned.objects.create(owner=alice)

    assert IsOwner().has_object_permission(_request("GET", alice), None, obj) is True


def test_is_owner_denies_shared_user_even_to_read(alice, bob):
    """No safe-method carve-out: IsOwner is owner-only for every verb, including GET — this is
    what guards a sensitive endpoint like the share audience list.
    """
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    assert IsOwner().has_object_permission(_request("GET", bob), None, obj) is False


def test_is_owner_denies_everyone_on_system_object(admin):
    obj = DummyOwned.objects.create(owner=None, is_system=True)

    assert IsOwner().has_object_permission(_request("GET", admin), None, obj) is False


def test_is_owner_denies_anonymous_on_ownerless_object():
    """Same fail-closed requirement as ``IsOwnerOrReadOnly`` (blocking finding 3): an anonymous
    request's ``id`` and an ownerless row's ``owner_id`` must never be allowed to compare equal
    as ``None == None``.
    """
    obj = DummyOwned(owner_id=None, is_system=False)

    result = IsOwner().has_object_permission(_request("DELETE", AnonymousUser()), None, obj)

    assert result is False


# --- CanCopy -------------------------------------------------------------------------------


def test_can_copy_own_object(alice):
    obj = DummyOwned.objects.create(owner=alice)

    assert CanCopy().has_object_permission(_request("POST", alice), None, obj) is True


def test_can_copy_shared_object(alice, bob):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    assert CanCopy().has_object_permission(_request("POST", bob), None, obj) is True


def test_can_copy_public_object(alice, carol):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)

    assert CanCopy().has_object_permission(_request("POST", carol), None, obj) is True


def test_can_copy_system_object(admin):
    obj = DummyOwned.objects.create(owner=None, is_system=True)

    assert CanCopy().has_object_permission(_request("POST", admin), None, obj) is True


def test_cannot_copy_private_object_not_shared(alice, carol):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PRIVATE)

    assert CanCopy().has_object_permission(_request("POST", carol), None, obj) is False


def test_cannot_copy_as_anonymous(alice):
    obj = DummyOwned.objects.create(owner=alice, visibility=Visibility.PUBLIC)

    result = CanCopy().has_object_permission(_request("POST", AnonymousUser()), None, obj)

    assert result is False
