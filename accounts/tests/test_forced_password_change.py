"""Tests for ForcePasswordChangeMiddleware (subtask 01.5).

Two test-plan entries are deliberately absent here rather than stubbed:
``test_after_change_normal_access_restored`` and ``test_expired_temp_password_rejected``
both need the real login view and the password-change view from subtask 01.6 to exercise
("log in", "the change form actually clears the flag through a POST") — this task only
carries a placeholder view (see accounts/views.py). They belong in 01.6.
"""

import pytest
from django.contrib.auth import get_user
from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, reverse

from accounts.middleware import LOGOUT_PATH, ForcePasswordChangeMiddleware
from accounts.services import complete_password_change

pytestmark = pytest.mark.django_db


def test_temp_password_user_redirected_to_change(client, user_factory):
    """Any app URL redirects — proven with a path that doesn't even resolve.

    The middleware short-circuits before URL resolution, so an arbitrary unrouted path proves
    the test-plan's actual wording ("any app URL redirects") without coupling to
    ``django.contrib.admin`` being installed or to admin's own login redirect not shadowing
    this one.
    """
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.get("/some/unrouted/path/")

    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change")


def test_change_form_itself_not_redirected(client, user_factory):
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.get(reverse("accounts:password_change"))

    assert response.status_code != 302


def test_logout_not_redirected(client, user_factory):
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.post("/accounts/logout/")

    # The logout view itself doesn't exist until 01.6 (a bare 404 here is expected), but the
    # middleware must never be the reason this path redirects to the change form.
    assert response.get("Location") != reverse("accounts:password_change")


def test_api_returns_403_not_redirect(client, user_factory):
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.get("/api/schema/")

    assert response.status_code == 403
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"detail": "password_change_required"}


def test_session_cycled_on_password_change(client, user_factory):
    """The pre-change session key no longer authenticates — a stolen session dies at reset.

    This proves the mechanism design.md relies on: changing the stored password hash means the
    session's stored auth hash no longer matches, and Django's own ``get_user()`` flushes the
    session the next time it is checked — no explicit revocation needed. The flush is driven by
    an actual request (``get_user()`` runs inside ``AuthenticationMiddleware`` on every
    request), and only then does the client's session cookie reflect it, so the probe request
    is what proves the mechanism rather than a direct, request-less call to ``get_user()``.
    Named directly rather than inferred from a status code, since ``!= 200`` would also be
    satisfied by an unrelated 500.
    """
    user = user_factory()
    client.force_login(user)
    session_key_before = client.session.session_key
    assert session_key_before is not None

    complete_password_change(user, "BrandNewPassw0rd!")
    client.get("/healthz/")

    assert client.session.session_key is None
    assert get_user(client).is_anonymous


def test_static_and_healthz_exempt(client, user_factory):
    user = user_factory(must_change_password=True)
    client.force_login(user)

    healthz_response = client.get("/healthz/")
    static_response = client.get("/static/some-file.css")
    media_response = client.get("/media/some-file.png")

    assert healthz_response.status_code != 302
    assert static_response.status_code != 302
    assert media_response.status_code != 302


def test_logout_exemption_matches_hardcoded_fallback():
    """The middleware's exemption tries ``reverse("accounts:logout")`` before falling back to
    the hardcoded ``LOGOUT_PATH`` constant (see accounts/middleware.py). Subtask 01.6 hasn't
    mounted a logout route yet, so this is vacuous today — the ``NoReverseMatch`` branch is
    taken and there is nothing to compare. The moment 01.6 mounts ``accounts:logout``
    somewhere other than ``LOGOUT_PATH``, ``reverse()`` here succeeds and the assertion below
    goes red, catching the drift immediately instead of via a silent "logout doesn't log you
    out" bug.
    """
    try:
        logout_path = reverse("accounts:logout")
    except NoReverseMatch:
        pytest.skip("accounts:logout not mounted yet (subtask 01.6)")

    assert logout_path == LOGOUT_PATH


def test_missing_authentication_middleware_raises(rf):
    """If ``ForcePasswordChangeMiddleware`` is ever reordered above ``AuthenticationMiddleware``
    (or that middleware is removed), ``request.user`` never gets set. The middleware must raise
    ``ImproperlyConfigured`` immediately rather than silently skipping enforcement — the same
    convention ``AuthenticationMiddleware`` itself uses when ``SessionMiddleware`` is missing.
    """
    request = rf.get("/some/path/")
    assert not hasattr(request, "user")
    middleware = ForcePasswordChangeMiddleware(get_response=lambda r: None)

    with pytest.raises(ImproperlyConfigured):
        middleware(request)
