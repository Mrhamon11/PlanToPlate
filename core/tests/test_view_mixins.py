"""Plan/03-Ownership-And-Sharing/test-plan.md, "HTML views — core/tests/test_view_mixins.py"
(03.9). Exercises ``OwnedObjectMixin`` (core/mixins.py) through throwaway Django generic views
(``core/tests/views.py``) over the same ``DummyOwned`` fixture the API's own IDOR suite
(core/tests/test_idor.py) uses — the two suites prove the two different front doors to the same
data agree, which is the whole point of ``OwnedObjectMixin`` existing at all (design.md: "The
HTML views must not have a second, weaker path to the data").
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from rest_framework.test import APIClient

from core.models import Visibility

pytestmark = [pytest.mark.django_db, pytest.mark.urls("core.tests.urls")]


def _client_for(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_html_list_view_filters_by_visibility(alice, carol, make_dummy):
    make_dummy(owner=alice, visibility=Visibility.PRIVATE, name="alices-secret")
    mine = make_dummy(owner=carol, name="carols-own")

    response = _client_for(carol).get("/dummy-html/")

    assert response.status_code == 200
    assert list(response.context["object_list"]) == [mine]


def test_html_detail_view_404s_on_invisible(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).get(f"/dummy-html/{obj.pk}/")

    assert response.status_code == 404


def test_html_detail_view_200s_on_visible(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(alice).get(f"/dummy-html/{obj.pk}/")

    assert response.status_code == 200


# --- the write-side secondary defence, added alongside the queryset scoping ------------------


def test_html_update_view_denies_non_owner_write(alice, bob, make_dummy):
    """A shared (visible) but non-owned object: POSTing an edit is denied -- the same split
    the API enforces for PUT/PATCH (test_permissions.py::test_shared_user_cannot_write), reached
    here through IsOwnerOrReadOnly directly rather than a re-derived rule.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED, name="original")
    obj.shared_with.add(bob)

    response = _client_for(bob).post(f"/dummy-html/{obj.pk}/edit/", {"name": "hijacked"})

    assert response.status_code == 403
    obj.refresh_from_db()
    assert obj.name == "original"


def test_html_update_view_404s_on_invisible_object(alice, carol, make_dummy):
    """The primary defence: an invisible object never even reaches the write-permission check
    -- it 404s at get_queryset(), the same enumeration-safe posture the API has.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    response = _client_for(carol).post(f"/dummy-html/{obj.pk}/edit/", {"name": "hijacked"})

    assert response.status_code == 404


def test_html_update_view_allows_owner_write(alice, make_dummy):
    obj = make_dummy(owner=alice, name="original")

    response = _client_for(alice).post(f"/dummy-html/{obj.pk}/edit/", {"name": "updated"})

    assert response.status_code == 302
    obj.refresh_from_db()
    assert obj.name == "updated"


# --- HTML and API agreement ---------------------------------------------------------------


def test_html_and_api_agree_on_visibility(alice, carol, make_dummy):
    """The same user, the same object, both paths -- identical verdict (design.md; guards
    against the HTML side growing a weaker query than the API).
    """
    visible_obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)
    invisible_obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    html_client = _client_for(carol)
    api_client = APIClient()
    api_client.force_login(carol)

    for obj, expected_status in ((visible_obj, 200), (invisible_obj, 404)):
        html_response = html_client.get(f"/dummy-html/{obj.pk}/")
        api_response = api_client.get(f"/dummy/{obj.pk}/")
        assert html_response.status_code == expected_status
        assert api_response.status_code == expected_status


# --- OwnedObjectMixin.get_form_class() closes the HTML-side write path (03.8a rework, ------
# security finding 4) -- the counterpart of OwnedSerializer making owner/is_system/shared_with/
# copied_from/visibility read-only on the API side (core/serializers.py).


def test_owned_object_mixin_refuses_form_that_exposes_unsafe_fields():
    """DummyUnsafeUpdateView (core/tests/views.py) lists `visibility` in `fields` -- exactly the
    field OwnedSerializer makes read-only for the same reason (changing it must go through
    core.services.sharing's cascade-refusal check, which a bare form POST has no way to run).
    """
    from core.tests.views import DummyUnsafeUpdateView

    view = DummyUnsafeUpdateView()

    with pytest.raises(ImproperlyConfigured, match="visibility"):
        view.get_form_class()


def test_owned_object_mixin_allows_a_form_with_only_safe_fields():
    """Non-vacuousness: the real DummyUpdateView (fields=["name"]) must not be flagged -- proves
    the check above is about the specific unsafe fields, not about get_form_class() erroring on
    every form.
    """
    from core.tests.views import DummyUpdateView

    view = DummyUpdateView()

    assert view.get_form_class() is not None
