"""Plan/03-Ownership-And-Sharing/test-plan.md, "IDOR matrix — core/tests/test_idor.py".

Exercises ``OwnedViewSetMixin`` (03.8) through a live route table
(``core/tests/urls.py``, activated per-module below) against the throwaway ``DummyOwned``
resource — this is the suite that exists to catch the single most likely serious bug in the
project: a queryset or serializer that leaks another user's private row.
"""

from __future__ import annotations

import itertools

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.permissions import BasePermission
from rest_framework.test import APIClient

from core.models import Visibility
from core.services.graph import MAX_DEPTH
from core.tests.models import DummyOwned

pytestmark = [pytest.mark.django_db, pytest.mark.urls("core.tests.urls")]


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


def test_cannot_retrieve_others_private(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).get(f"/dummy/{obj.pk}/")

    assert response.status_code == 404


@pytest.mark.parametrize("method", ["put", "patch"])
def test_cannot_update_others_object(alice, carol, make_dummy, method):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE, name="original")
    client = _client_for(carol)

    response = getattr(client, method)(f"/dummy/{obj.pk}/", {"name": "hijacked"})

    assert response.status_code == 404
    obj.refresh_from_db()
    assert obj.name == "original"


def test_cannot_delete_others_object(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).delete(f"/dummy/{obj.pk}/")

    assert response.status_code == 404
    assert DummyOwned.objects.filter(pk=obj.pk).exists()


def test_list_excludes_others_private(alice, carol, make_dummy):
    make_dummy(owner=alice, visibility=Visibility.PRIVATE, name="alices-secret")
    mine = make_dummy(owner=carol, name="carols-own")

    response = _client_for(carol).get("/dummy/")

    ids = {row["id"] for row in response.data["results"]}
    assert ids == {mine.pk}


def test_cannot_set_owner_on_create(alice, bob):
    response = _client_for(alice).post("/dummy/", {"name": "new", "owner": bob.pk})

    assert response.status_code == 201
    created = DummyOwned.objects.get(pk=response.data["id"])
    assert created.owner == alice


def test_cannot_set_is_system_on_create(alice):
    response = _client_for(alice).post("/dummy/", {"name": "new", "is_system": True})

    assert response.status_code == 201
    created = DummyOwned.objects.get(pk=response.data["id"])
    assert created.is_system is False
    assert created.owner == alice


def test_cannot_inject_shared_with_on_update(alice, bob, make_dummy):
    obj = make_dummy(owner=alice)

    response = _client_for(alice).patch(f"/dummy/{obj.pk}/", {"shared_with": [bob.pk]})

    assert response.status_code == 200
    obj.refresh_from_db()
    assert obj.shared_with.count() == 0


def test_cannot_change_visibility_via_patch(alice, make_dummy):
    """Review finding (security #6 / correctness #4): visibility changes must go through
    ``/share/``, not a plain PATCH, since only the sharing service runs the cascade check.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(alice).patch(f"/dummy/{obj.pk}/", {"visibility": Visibility.PUBLIC})

    assert response.status_code == 200
    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


def test_filters_cannot_bypass_visibility(alice, carol, make_dummy):
    make_dummy(owner=alice, visibility=Visibility.PRIVATE, name="alices-secret")
    mine = make_dummy(owner=carol, name="carols-own")
    client = _client_for(carol)

    # Each filter narrows visible_to(carol) further; alice's private object must never appear
    # regardless of which narrowing is requested. mine=true and ordering=-id both keep carol's
    # own row (it satisfies "owner=carol", and ordering applies no predicate at all); public=
    # true and shared_with_me=true correctly narrow it away too, since mine is neither PUBLIC
    # nor shared with carol by herself. Pinned per-query (03.8a / NB10) rather than the previous
    # blanket `ids <= {mine.pk}`, which an empty response also satisfied for every query and so
    # would not have caught mine=true or ordering=-id silently degrading to zero results.
    expected_ids_by_query = {
        "?mine=true": {mine.pk},
        "?public=true": set(),
        "?shared_with_me=true": set(),
        "?ordering=-id": {mine.pk},
    }

    for query, expected_ids in expected_ids_by_query.items():
        response = client.get(f"/dummy/{query}")
        ids = {row["id"] for row in response.data["results"]}
        assert ids == expected_ids, f"visibility bypassed via {query!r}: got ids {ids}"


# --- share / unshare / copy actions, wired end-to-end ---------------------------------------


def test_share_action_grants_access(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)

    response = _client_for(alice).post(f"/dummy/{obj.pk}/share/", {"users": [bob.pk]})

    assert response.status_code == 200
    assert response.data["shared_with"] == [bob.pk]
    assert DummyOwned.objects.visible_to(bob).filter(pk=obj.pk).exists()


def test_share_action_is_owner_only(alice, bob, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    response = _client_for(bob).post(f"/dummy/{obj.pk}/share/", {"users": [carol.pk]})

    assert response.status_code == 403
    assert carol not in obj.shared_with.all()


def test_share_action_404s_on_invisible_object(alice, carol, make_dummy):
    """Carol cannot see the object at all — this must 404, not 403, before ``IsOwner`` is
    ever consulted (design.md, "Enumeration"; a 403 would confirm the object exists).
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).post(f"/dummy/{obj.pk}/share/", {"users": [carol.pk]})

    assert response.status_code == 404
    assert obj.shared_with.count() == 0


def test_share_action_rejects_ungrantable_cascade(alice, bob, carol, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PRIVATE)
    parent.depends_on.add(foreign_child)

    response = _client_for(alice).post(f"/dummy-nodes/{parent.pk}/share/", {"users": [bob.pk]})

    assert response.status_code == 400
    assert "child" in response.data["detail"]
    assert parent.shared_with.count() == 0


def test_unshare_action_revokes_access(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    response = _client_for(alice).post(f"/dummy/{obj.pk}/unshare/", {"users": [bob.pk]})

    assert response.status_code == 204
    assert not DummyOwned.objects.visible_to(bob).filter(pk=obj.pk).exists()


def test_unshare_action_is_owner_only(alice, bob, carol, make_dummy):
    """A share-holder (visible, non-owner) cannot revoke access — the direct analogue of
    ``test_share_action_is_owner_only``, at the endpoint layer.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob, carol)

    response = _client_for(bob).post(f"/dummy/{obj.pk}/unshare/", {"users": [carol.pk]})

    assert response.status_code == 403
    assert set(obj.shared_with.all()) == {bob, carol}


def test_unshare_action_404s_on_invisible_object(alice, carol, make_dummy):
    """Carol cannot see the object at all — this must 404, not 403 (design.md,
    "Enumeration").
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).post(f"/dummy/{obj.pk}/unshare/", {"users": [carol.pk]})

    assert response.status_code == 404


def test_copy_action_creates_private_copy_for_any_visible_user(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC, name="original")

    response = _client_for(bob).post(f"/dummy/{obj.pk}/copy/")

    assert response.status_code == 201
    copy = DummyOwned.objects.get(pk=response.data["id"])
    assert copy.owner == bob
    assert copy.visibility == Visibility.PRIVATE
    assert copy.copied_from_id == obj.pk


def test_copy_action_404s_on_invisible_object(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).post(f"/dummy/{obj.pk}/copy/")

    assert response.status_code == 404


# --- anonymous access -------------------------------------------------------------------------
# Security review finding #1: OwnedViewSetMixin's permission_classes/filter_backends replaced
# rather than composed with DEFAULT_PERMISSION_CLASSES, dropping IsAuthenticated (and
# ForcePasswordChangeAPIPermission) from every owned endpoint.


def test_anonymous_cannot_list(alice, make_dummy):
    make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    response = APIClient().get("/dummy/")

    assert response.status_code in (401, 403)


def test_anonymous_cannot_use_mine_filter(alice, make_dummy):
    """Pre-fix this raised a 500 (``TypeError``, an ``AnonymousUser`` fed to an ``id`` lookup) —
    the filter backend never should have run at all for an unauthenticated request.
    """
    make_dummy(owner=alice)

    response = APIClient().get("/dummy/?mine=true")

    assert response.status_code in (401, 403)


def test_anonymous_cannot_create():
    """Pre-fix this raised a 500 (``ValueError`` assigning ``AnonymousUser`` as ``owner``)."""
    response = APIClient().post("/dummy/", {"name": "new"})

    assert response.status_code in (401, 403)


def test_anonymous_cannot_retrieve(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    response = APIClient().get(f"/dummy/{obj.pk}/")

    assert response.status_code in (401, 403)


@pytest.mark.parametrize(
    ("method", "action"),
    [("post", "share"), ("post", "unshare"), ("post", "copy"), ("get", "shares")],
)
def test_anonymous_cannot_use_any_action(alice, make_dummy, method, action):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    response = getattr(APIClient(), method)(f"/dummy/{obj.pk}/{action}/", {})

    assert response.status_code in (401, 403)


# --- GraphError at the API boundary ------------------------------------------------------------
# Review finding (correctness #3 / security #5): CycleError/DepthExceededError must become a
# 400 with the exception's message, not a 500, on both the share and copy actions.


def test_share_action_maps_dependency_cycle_to_400(alice, bob, make_dummy_node):
    a = make_dummy_node(owner=alice, name="a")
    b = make_dummy_node(owner=alice, name="b")
    a.depends_on.add(b)
    b.depends_on.add(a)

    response = _client_for(alice).post(f"/dummy-nodes/{a.pk}/share/", {"users": [bob.pk]})

    assert response.status_code == 400


def test_share_action_maps_depth_exceeded_to_400(alice, bob, make_dummy_node):
    nodes = [make_dummy_node(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 3)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)

    response = _client_for(alice).post(f"/dummy-nodes/{nodes[0].pk}/share/", {"users": [bob.pk]})

    assert response.status_code == 400


def test_copy_action_maps_dependency_cycle_to_400(alice, make_dummy_node):
    a = make_dummy_node(owner=alice, name="a")
    b = make_dummy_node(owner=alice, name="b")
    a.depends_on.add(b)
    b.depends_on.add(a)

    response = _client_for(alice).post(f"/dummy-nodes/{a.pk}/copy/")

    assert response.status_code == 400


def test_copy_action_maps_depth_exceeded_to_400(alice, make_dummy_node):
    nodes = [make_dummy_node(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 3)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)

    response = _client_for(alice).post(f"/dummy-nodes/{nodes[0].pk}/copy/")

    assert response.status_code == 400


def test_copy_action_reports_hollow_container_as_400_not_404(alice, bob, carol, make_dummy_node):
    """Review finding (correctness #4 / design.md "Edge cases"): a visible parent whose own
    child drifts out of visibility after being shared must fail loudly with a 400, not read as
    "the object you asked for does not exist" via a bare 404 on an object bob is looking at.
    """
    parent = make_dummy_node(owner=alice, name="parent", visibility=Visibility.SHARED)
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PUBLIC)
    parent.depends_on.add(foreign_child)
    share_response = _client_for(alice).post(
        f"/dummy-nodes/{parent.pk}/share/", {"users": [bob.pk]}
    )
    assert share_response.status_code == 200

    foreign_child.visibility = Visibility.PRIVATE
    foreign_child.save(update_fields=["visibility"])

    response = _client_for(bob).post(f"/dummy-nodes/{parent.pk}/copy/")

    assert response.status_code == 400


# --- visibility validation on /share/ ----------------------------------------------------------
# Review finding (correctness #2 / security #4): visibility must be a ChoiceField, not a bare
# CharField, so garbage never reaches the database.


def test_share_action_rejects_invalid_visibility_choice(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(alice).post(f"/dummy/{obj.pk}/share/", {"visibility": "public"})

    assert response.status_code == 400
    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


def test_share_action_rejects_overlong_visibility_string(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(alice).post(f"/dummy/{obj.pk}/share/", {"visibility": "X" * 80})

    assert response.status_code == 400
    obj.refresh_from_db()
    assert obj.visibility == Visibility.PRIVATE


# --- force-password-change composition at the core/ level (03.8a / NB4) ----------------------
# get_permissions() (core/viewsets.py) composes DEFAULT_PERMISSION_CLASSES, which includes
# ForcePasswordChangeAPIPermission, onto every owned endpoint. A session-authenticated request
# never actually reaches that permission class in practice — ForcePasswordChangeMiddleware
# already blocks it earlier, before Django's URL resolver even runs (accounts/middleware.py) —
# so the only way to exercise the permission class itself is a token-authenticated request: the
# middleware sees an AnonymousUser (TokenAuthentication only runs inside DRF's own
# APIView.initial(), after the middleware), and reaches this permission with the real user.


def test_force_password_change_permission_blocks_token_authenticated_owned_viewset_request(
    alice, make_dummy
):
    """Also proves the NB4 fail-closed fix: core.tests.urls carries no accounts_api routes, so
    ``api_password_change_path()``'s ``reverse()`` call cannot resolve here. Pre-fix this raised
    ``NoReverseMatch`` (an unhandled 500); post-fix it must deny cleanly (403).
    """
    from rest_framework.authtoken.models import Token

    alice.must_change_password = True
    alice.save(update_fields=["must_change_password"])
    token = Token.objects.create(user=alice)
    obj = make_dummy(owner=alice)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    response = client.get(f"/dummy/{obj.pk}/")

    assert response.status_code == 403


def test_force_password_change_permission_allows_token_authenticated_user_without_the_flag(
    alice, make_dummy
):
    """Non-vacuousness check: the same token-authenticated path, without ``must_change_password``
    set, must succeed — proving the 403 above is the permission actually firing, not some
    unrelated breakage in token authentication against ``core.tests.urls``.
    """
    from rest_framework.authtoken.models import Token

    token = Token.objects.create(user=alice)
    obj = make_dummy(owner=alice)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    response = client.get(f"/dummy/{obj.pk}/")

    assert response.status_code == 200


# --- get_permissions() reads DEFAULT_PERMISSION_CLASSES live (03.8a / NB5) --------------------
# core/viewsets.py's own docstring on get_permissions() explains why this must be a live read
# rather than a module-level snapshot taken once when core.viewsets first imports: a snapshot
# would freeze in whatever DEFAULT_PERMISSION_CLASSES happened to be at that moment, long before
# any override_settings block here runs, so a permission class added afterward would never be
# consulted and a request meant to be blocked would silently succeed instead. Proven end-to-end
# through the live /dummy/ route DummyOwnedViewSet serves, not by inspecting
# get_permissions()'s return value in isolation, so this exercises the exact code path real
# traffic uses.


class _DenyAllPermission(BasePermission):
    """A marker permission with no purpose but to prove whether it was actually consulted."""

    def has_permission(self, request, view) -> bool:
        return False


def test_get_permissions_reads_default_permission_classes_live(alice, make_dummy):
    """Mutation guard: reverting ``get_permissions()`` to read a module-level snapshot of
    ``api_settings.DEFAULT_PERMISSION_CLASSES`` (the pre-fix shape) makes the middle assertion
    fail — the override below is appended to ``DEFAULT_PERMISSION_CLASSES`` well after
    ``core.viewsets`` first imported, so only a live read on every call can see it.
    """
    make_dummy(owner=alice, visibility=Visibility.PUBLIC)
    client = _client_for(alice)

    baseline = client.get("/dummy/")
    assert baseline.status_code == 200

    with override_settings(
        REST_FRAMEWORK={
            **settings.REST_FRAMEWORK,
            "DEFAULT_PERMISSION_CLASSES": [
                *settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
                "core.tests.test_idor._DenyAllPermission",
            ],
        }
    ):
        blocked = client.get("/dummy/")
    assert blocked.status_code == 403

    # And the override does not outlive its `with` block: the same client, object, and action
    # succeed again once DEFAULT_PERMISSION_CLASSES reverts -- proving the 403 above really was
    # this test's override firing, not some unrelated breakage.
    after = client.get("/dummy/")
    assert after.status_code == 200


# --- get_permissions() composes an explicit permission_classes override additively -------------
# (03.8a rework, security finding 2) -- the pre-fix get_permissions() only ever built
# [*DEFAULT_PERMISSION_CLASSES, mixin's own per-action default], silently discarding both a
# subclass's own `permission_classes` class attribute and an `@action(...,
# permission_classes=[...])` kwarg. Both shapes are proven end-to-end here, through the live
# routes DummyOwnedViewSet/DummyClassLevelAdminViewSet serve, not by inspecting
# get_permissions()'s return value in isolation.


def test_action_level_permission_classes_override_is_composed(alice, admin, make_dummy):
    """``@action(..., permission_classes=[IsAdminUser])`` on ``admin_only`` (core/tests/
    viewsets.py) must actually gate the action -- pre-fix, an owner who is not staff could call
    it, since IsAdminUser was silently dropped in favour of IsOwnerOrReadOnly.
    """
    obj = make_dummy(owner=alice)

    owner_response = _client_for(alice).post(f"/dummy/{obj.pk}/admin_only/")
    admin_response = _client_for(admin).post(f"/dummy/{obj.pk}/admin_only/")

    assert owner_response.status_code == 403
    assert admin_response.status_code == 204


def test_class_level_permission_classes_override_is_composed(alice, admin, make_dummy):
    """A subclass declaring ``permission_classes = [IsAdminUser]``
    (``DummyClassLevelAdminViewSet``) must gate every action, including plain list/retrieve --
    pre-fix, the class attribute was never consulted at all.
    """
    make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    owner_response = _client_for(alice).get("/dummy-admin-only/")
    admin_response = _client_for(admin).get("/dummy-admin-only/")

    assert owner_response.status_code == 403
    assert admin_response.status_code == 200


# --- get_permissions() composes an explicit override *on top of*, never in place of, the -------
# mixin's own baseline (03.8a rework, iteration-3 review blocking finding 1) -- the fix above
# for the previous round's finding 2 over-corrected: composing `[*DEFAULT_PERMISSION_CLASSES,
# *self.permission_classes]` whenever a declaration existed *dropped* `_ACTION_PERMISSION_CLASSES`
# entirely, so IsOwnerOrReadOnly/IsOwner silently vanished the moment any subclass or @action
# declared its own permission_classes -- reopening the flagship IDOR on DELETE and the
# owner-only /shares/ audience list, the exact failure the reviewer drove end to end with
# APIRequestFactory against a viewset declaring `permission_classes = [IsAuthenticated]`.


def test_class_level_authenticated_only_override_does_not_drop_the_ownership_baseline(
    alice, bob, make_dummy
):
    """The reviewer's exact repro: bob holds only a *read-only* share of alice's object
    (visible via `.visible_to()`, so `get_object()` succeeds and `get_permissions()` is what
    must deny him), against a viewset (`DummyClassLevelAuthenticatedOnlyViewSet`) declaring
    `permission_classes = [IsAuthenticated]` -- a declaration that reads as tightening, not
    replacing, the mixin's own IsOwnerOrReadOnly/IsOwner baseline. Pre-fix: DELETE returned 204
    (row actually deleted) and GET .../shares/ returned 200 with the full audience list.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)
    client = _client_for(bob)

    delete_response = client.delete(f"/dummy-authenticated-only/{obj.pk}/")
    shares_response = client.get(f"/dummy-authenticated-only/{obj.pk}/shares/")

    assert delete_response.status_code == 403
    assert DummyOwned.objects.filter(pk=obj.pk).exists()
    assert shares_response.status_code == 403


def test_class_level_authenticated_only_override_still_lets_the_owner_through(alice, make_dummy):
    """Non-vacuousness pair for the test above: the same viewset, viewed by the object's real
    owner, must still permit DELETE and the /shares/ list -- proving the 403s above are the
    ownership baseline firing, not `IsAuthenticated` (or something else) blocking everyone.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)
    client = _client_for(alice)

    shares_response = client.get(f"/dummy-authenticated-only/{obj.pk}/shares/")
    delete_response = client.delete(f"/dummy-authenticated-only/{obj.pk}/")

    assert shares_response.status_code == 200
    assert delete_response.status_code == 204
    assert not DummyOwned.objects.filter(pk=obj.pk).exists()
