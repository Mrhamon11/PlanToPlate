"""Tests for ForcePasswordChangeMiddleware (subtask 01.5) and the forced-reset flow it guards,
completed in subtask 01.6 now that the real login and password-change views exist.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from django.utils import timezone

from accounts.middleware import ForcePasswordChangeMiddleware
from accounts.services import complete_password_change, temp_password_expired

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
    """A user forced to change their password can still leave — the exempt logout path must
    never be shadowed by the change-form redirect.
    """
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.post(reverse("accounts:logout"))

    assert response.get("Location") != reverse("accounts:password_change")
    assert get_user(client).is_anonymous


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


def test_after_change_normal_access_restored(client, user_factory):
    """01.6's single bolded requirement: the acting session survives the change.

    ``update_session_auth_hash`` *cycles* the session (a fresh key, to defeat session fixation)
    but does not flush it — unlike a bare ``set_password``, which would kill every session for
    the user, including this one. Asserted directly against the same client/session that made
    the POST, with no intervening re-login, and against a route
    (``accounts:profile``) that ``ForcePasswordChangeMiddleware`` does not exempt — ``/healthz/``
    is exempt unconditionally regardless of ``must_change_password``, so a probe against it would
    pass even if the forced-reset loop never actually ended.
    """
    user = user_factory(must_change_password=True)
    client.force_login(user)
    session_key_before = client.session.session_key

    response = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": "testpass123",
            "new_password1": "BrandNewPassw0rd!",
            "new_password2": "BrandNewPassw0rd!",
        },
    )
    assert response.status_code == 302

    assert get_user(client).is_authenticated
    assert client.session.session_key is not None
    assert client.session.session_key != session_key_before

    user.refresh_from_db()
    assert user.must_change_password is False

    follow_up = client.get(reverse("accounts:profile"))
    assert follow_up.status_code == 200


def test_expired_temp_password_rejected(client, user_factory):
    user = user_factory(password="StillCorrectPassw0rd!")
    user.must_change_password = True
    user.temp_password_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["must_change_password", "temp_password_expires_at"])
    assert temp_password_expired(user) is True

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "StillCorrectPassw0rd!"},
    )

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated
    assert "expired" in str(response.context["form"].errors).lower()


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
