"""Plan/03-Ownership-And-Sharing/test-plan.md, "Sharing service — core/tests/test_sharing.py".

Exercises ``core.services.sharing`` directly (the service is the enforcement point regardless
of whether a caller is a REST viewset, an HTML view, or a management command), plus the
``/shares/`` list endpoint's owner-only posture, which needs a live route (03.8) to demonstrate.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.models import Visibility
from core.services.graph import GraphError
from core.services.sharing import ShareResult, SharingError, set_visibility, share, unshare
from core.tests.models import DummyNode, DummyOwned

pytestmark = pytest.mark.django_db


# --- share() -----------------------------------------------------------------------------


def test_owner_can_share(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)

    result = share(obj, actor=alice, users=[bob])

    assert isinstance(result, ShareResult)
    assert list(obj.shared_with.all()) == [bob]
    assert DummyOwned.objects.visible_to(bob).filter(pk=obj.pk).exists()


@pytest.mark.urls("core.tests.urls")
def test_share_rejects_deactivated_user_via_api(alice, bob, make_dummy):
    """NB9: a deactivated account must not be a valid share target — accepting it would give an
    invalid-vs-valid pk a 400-vs-success oracle over the full user table, inactive accounts
    included.
    """
    bob.is_active = False
    bob.save()
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)

    client = APIClient()
    client.force_login(alice)
    response = client.post(f"/dummy/{obj.pk}/share/", {"users": [bob.pk]})

    assert response.status_code == 400
    assert obj.shared_with.count() == 0


def test_non_owner_cannot_share(alice, bob, carol, make_dummy):
    """The core anti-reshare rule: a user merely holding a share cannot grant it onward."""
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    with pytest.raises(PermissionDenied):
        share(obj, actor=bob, users=[carol])

    assert list(obj.shared_with.all()) == [bob]


def test_cannot_share_system_object(admin, bob, make_dummy):
    obj = make_dummy(owner=None, is_system=True)

    with pytest.raises(PermissionDenied):
        share(obj, actor=admin, users=[bob])

    assert obj.shared_with.count() == 0


def test_share_with_self_is_noop(alice, make_dummy):
    obj = make_dummy(owner=alice)

    result = share(obj, actor=alice, users=[alice])

    assert result.users == []
    assert obj.shared_with.count() == 0


def test_share_cascades_to_children(alice, bob, make_dummy_node):
    """Sharing a container grants read on its children, transitively to the second level."""
    grandparent = make_dummy_node(owner=alice, name="grandparent")
    parent = make_dummy_node(owner=alice, name="parent")
    child = make_dummy_node(owner=alice, name="child")
    grandparent.depends_on.add(parent)
    parent.depends_on.add(child)

    share(grandparent, actor=alice, users=[bob])

    assert DummyNode.objects.visible_to(bob).filter(pk=grandparent.pk).exists()
    assert DummyNode.objects.visible_to(bob).filter(pk=parent.pk).exists()
    assert DummyNode.objects.visible_to(bob).filter(pk=child.pk).exists()


def test_share_refused_when_child_not_grantable(alice, bob, carol, make_dummy_node):
    """A child owned by someone else and invisible to the target refuses the whole share, and
    the error names the blocking object.
    """
    parent = make_dummy_node(owner=alice, name="Sunday Roast")
    foreign_child = make_dummy_node(owner=carol, name="Nan's Gravy", visibility=Visibility.PRIVATE)
    parent.depends_on.add(foreign_child)

    with pytest.raises(SharingError) as exc_info:
        share(parent, actor=alice, users=[bob])

    message = str(exc_info.value)
    assert "Sunday Roast" in message
    assert "Nan's Gravy" in message
    assert str(bob) in message
    assert parent.shared_with.count() == 0


def test_share_succeeds_when_foreign_child_already_visible(alice, bob, carol, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PUBLIC)
    parent.depends_on.add(foreign_child)

    share(parent, actor=alice, users=[bob])

    assert DummyNode.objects.visible_to(bob).filter(pk=parent.pk).exists()
    # The foreign child was never actor's to grant — it stays ungranted, just already visible.
    assert bob not in foreign_child.shared_with.all()


def test_share_cascade_terminates_on_cycle(alice, bob, make_dummy_node):
    a = make_dummy_node(owner=alice, name="a")
    b = make_dummy_node(owner=alice, name="b")
    a.depends_on.add(b)
    b.depends_on.add(a)

    with pytest.raises(GraphError):
        share(a, actor=alice, users=[bob])


# --- visibility validation -----------------------------------------------------------------


def test_share_rejects_invalid_visibility_value(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    with pytest.raises(SharingError):
        share(obj, actor=alice, visibility="public")

    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


def test_share_rejects_overlong_visibility_value(alice, make_dummy):
    """Reproduces the portability trap (CLAUDE.md section 6): SQLite silently stores a value
    longer than the column's ``max_length=16``; Postgres would raise ``DataError``. The service
    must refuse before ``save()`` ever runs, regardless of which database is behind it.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    with pytest.raises(SharingError):
        share(obj, actor=alice, visibility="X" * 80)

    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


def test_set_visibility_rejects_invalid_value(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    with pytest.raises(SharingError):
        set_visibility(obj, actor=alice, visibility="public")

    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


# --- widening visibility to PUBLIC runs the cascade too -------------------------------------


def test_share_visibility_public_bypass_is_blocked_like_per_user_share(
    alice, bob, carol, make_dummy_node
):
    """Reproduces the security review's exact finding: a per-user share of a container with a
    foreign, invisible-to-the-target dependency is correctly refused, but flipping the same
    container's visibility straight to PUBLIC used to skip the cascade check entirely and
    succeed — the "refuse loudly" guard bypassed by choosing the *broader* share. Both routes
    must refuse identically.
    """
    parent = make_dummy_node(owner=alice, name="parent")
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(foreign_child)

    with pytest.raises(SharingError):
        share(parent, actor=alice, users=[bob])

    with pytest.raises(SharingError):
        share(parent, actor=alice, visibility=Visibility.PUBLIC)

    parent.refresh_from_db()
    assert parent.visibility == Visibility.PRIVATE
    assert parent.shared_with.count() == 0


def test_share_widening_to_public_names_the_blocking_child(alice, carol, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="Sunday Roast")
    foreign_child = make_dummy_node(owner=carol, name="Nan's Gravy", visibility=Visibility.PRIVATE)
    parent.depends_on.add(foreign_child)

    with pytest.raises(SharingError) as exc_info:
        share(parent, actor=alice, visibility=Visibility.PUBLIC)

    assert "Nan's Gravy" in str(exc_info.value)
    parent.refresh_from_db()
    assert parent.visibility == Visibility.PRIVATE


def test_share_widening_to_public_succeeds_when_foreign_child_already_public(
    alice, carol, make_dummy_node
):
    parent = make_dummy_node(owner=alice, name="parent")
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PUBLIC)
    parent.depends_on.add(foreign_child)

    share(parent, actor=alice, visibility=Visibility.PUBLIC)

    parent.refresh_from_db()
    assert parent.visibility == Visibility.PUBLIC


def test_share_widening_to_public_cascades_to_actor_owned_children(alice, make_dummy_node):
    """The other half of the fix: an actor-owned dependency receives the equivalent grant
    rather than staying private underneath a now-public container.
    """
    parent = make_dummy_node(owner=alice, name="parent")
    own_child = make_dummy_node(owner=alice, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(own_child)

    share(parent, actor=alice, visibility=Visibility.PUBLIC)

    own_child.refresh_from_db()
    assert own_child.visibility == Visibility.PUBLIC


@pytest.mark.urls("core.tests.urls")
def test_share_response_reports_cascaded_to(alice, make_dummy_node):
    """NB1: the API response surfaces ``ShareResult.cascaded_to`` so a future UI (03.10) can
    warn the owner which of their own objects are about to be made PUBLIC alongside the
    container, rather than silently discarding that information.
    """
    parent = make_dummy_node(owner=alice, name="parent")
    own_child = make_dummy_node(owner=alice, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(own_child)

    client = APIClient()
    client.force_login(alice)
    response = client.post(f"/dummy-nodes/{parent.pk}/share/", {"visibility": Visibility.PUBLIC})

    assert response.status_code == 200
    assert response.data["cascaded_to"] == [own_child.pk]


def test_set_visibility_public_refuses_when_foreign_child_not_public(alice, carol, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(foreign_child)

    with pytest.raises(SharingError):
        set_visibility(parent, actor=alice, visibility=Visibility.PUBLIC)

    parent.refresh_from_db()
    assert parent.visibility == Visibility.PRIVATE


def test_set_visibility_public_cascades_to_actor_owned_children(alice, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    own_child = make_dummy_node(owner=alice, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(own_child)

    set_visibility(parent, actor=alice, visibility=Visibility.PUBLIC)

    own_child.refresh_from_db()
    assert own_child.visibility == Visibility.PUBLIC


# --- unshare() ---------------------------------------------------------------------------


def test_unshare_removes_access(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    share(obj, actor=alice, users=[bob])

    unshare(obj, actor=alice, users=[bob])

    assert not DummyOwned.objects.visible_to(bob).filter(pk=obj.pk).exists()


def test_unshare_does_not_cascade(alice, bob, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    child = make_dummy_node(owner=alice, name="child")
    parent.depends_on.add(child)
    share(parent, actor=alice, users=[bob])

    unshare(parent, actor=alice, users=[bob])

    assert not DummyNode.objects.visible_to(bob).filter(pk=parent.pk).exists()
    assert DummyNode.objects.visible_to(bob).filter(pk=child.pk).exists()


def test_unshare_with_no_users_is_a_noop(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    unshare(obj, actor=alice, users=[])

    assert list(obj.shared_with.all()) == [bob]


def test_non_owner_cannot_unshare(alice, bob, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob, carol)

    with pytest.raises(PermissionDenied):
        unshare(obj, actor=bob, users=[carol])

    assert set(obj.shared_with.all()) == {bob, carol}


# --- set_visibility() --------------------------------------------------------------------


def test_public_to_private_preserves_explicit_grants(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)
    share(obj, actor=alice, users=[bob])

    set_visibility(obj, actor=alice, visibility=Visibility.PRIVATE)

    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE
    assert list(obj.shared_with.all()) == [bob]
    assert DummyOwned.objects.visible_to(bob).filter(pk=obj.pk).exists()


def test_sharing_an_already_public_object_still_records_grants(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    share(obj, actor=alice, users=[bob])

    assert list(obj.shared_with.all()) == [bob]
    assert obj.visibility == Visibility.PUBLIC


def test_share_can_grant_users_and_change_visibility_in_one_call(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    share(obj, actor=alice, users=[bob], visibility=Visibility.SHARED)

    obj.refresh_from_db()
    assert obj.visibility == Visibility.SHARED
    assert list(obj.shared_with.all()) == [bob]


# --- /shares/ endpoint ---------------------------------------------------------------------


@pytest.mark.urls("core.tests.urls")
def test_shares_list_visible_to_owner_only(alice, bob, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    owner_client = APIClient()
    owner_client.force_login(alice)
    owner_response = owner_client.get(f"/dummy/{obj.pk}/shares/")
    assert owner_response.status_code == 200
    assert [row["id"] for row in owner_response.data] == [bob.pk]

    shared_client = APIClient()
    shared_client.force_login(bob)
    shared_response = shared_client.get(f"/dummy/{obj.pk}/shares/")
    assert shared_response.status_code == 403

    unrelated_client = APIClient()
    unrelated_client.force_login(carol)
    unrelated_response = unrelated_client.get(f"/dummy/{obj.pk}/shares/")
    assert unrelated_response.status_code == 404
