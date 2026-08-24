"""Tests for ``/api/auth/`` (subtask 01.7).

Login-throttle coverage is subtask 01.8's, not this file's.
"""

import base64

import pytest
from django.contrib.auth import get_user
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from conftest import DEFAULT_TEST_PASSWORD

pytestmark = pytest.mark.django_db


def test_api_login_sets_session(api_client, user_factory):
    user = user_factory()

    response = api_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )

    assert response.status_code == 200
    assert response.data["username"] == user.username
    assert get_user(api_client).is_authenticated


def test_api_login_rejects_bad_credentials(api_client, user_factory):
    user = user_factory()

    response = api_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "not-the-real-password"},
    )

    assert response.status_code == 400
    assert get_user(api_client).is_anonymous


def test_me_returns_current_user(authenticated_client):
    response = authenticated_client.get("/api/auth/me/")

    assert response.status_code == 200
    assert "must_change_password" in response.data
    assert "password" not in response.data


def test_me_requires_auth(api_client):
    response = api_client.get("/api/auth/me/")

    # 403, not 401: get_authenticate_header() consults get_authenticators()[0], which is
    # SessionAuthentication and returns None, so DRF converts NotAuthenticated to 403
    # regardless of which authenticator rejected the request — see
    # test_password_change_revokes_existing_tokens for the same nuance.
    assert response.status_code == 403


def test_api_logout_clears_session(authenticated_client):
    response = authenticated_client.post("/api/auth/logout/")

    assert response.status_code == 204
    assert get_user(authenticated_client).is_anonymous


def test_api_password_change_requires_old_password(authenticated_client):
    response = authenticated_client.post(
        "/api/auth/password/change/",
        {"old_password": "wrong-old-password", "new_password": "BrandNewPassw0rd!"},
    )

    assert response.status_code == 400
    assert "old_password" in response.data


def test_api_password_change_succeeds_and_clears_flags(api_client, user_factory):
    user = user_factory(must_change_password=True)
    api_client.force_login(user)
    session_key_before = api_client.session.session_key

    response = api_client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )

    assert response.status_code == 204
    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password("BrandNewPassw0rd!") is True
    # Design.md step 4: the view must call update_session_auth_hash immediately after
    # completing the change, or this same request's own session dies with it. Asserting the
    # key actually changed (not just that the client is still authenticated) proves it cycled
    # rather than merely surviving by coincidence.
    assert get_user(api_client).is_authenticated
    assert api_client.session.session_key is not None
    assert api_client.session.session_key != session_key_before


def test_no_endpoint_leaks_password_hash(api_client, user_factory):
    """Scans every auth response body for the plaintext password and the stored hash — not
    for the literal word "password", which legitimately appears as part of the
    ``must_change_password`` field name.
    """
    user = user_factory()
    hash_prefix = user.password.split("$")[0]

    login_response = api_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )
    me_response = api_client.get("/api/auth/me/")
    change_response = api_client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )

    for response in (login_response, me_response, change_response):
        content = response.content.decode()
        assert DEFAULT_TEST_PASSWORD not in content
        assert "BrandNewPassw0rd!" not in content
        assert user.password not in content
        assert hash_prefix not in content


def test_token_authenticated_request_succeeds(user_factory):
    user = user_factory()
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.get("/api/auth/me/")

    assert response.status_code == 200
    assert response.data["username"] == user.username


def test_basic_authentication_disabled(user_factory):
    user = user_factory()
    credentials = base64.b64encode(f"{user.username}:{DEFAULT_TEST_PASSWORD}".encode()).decode()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")

    response = client.get("/api/auth/me/")

    assert response.status_code == 403


def test_token_auth_blocked_when_must_change_password(user_factory):
    """The DRF-side counterpart to ForcePasswordChangeMiddleware (accounts/permissions.py).

    ForcePasswordChangeMiddleware never sees this user's identity — DRF authenticates the
    token inside APIView.initial(), after the middleware has already run — so without this
    permission, a must_change_password=True user with a valid token would get unrestricted
    API access (design.md, "Temp password flow" step 3).
    """
    user = user_factory(must_change_password=True)
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.get("/api/auth/me/")

    assert response.status_code == 403
    assert response.data["detail"] == "password_change_required"


def test_api_login_rejects_anonymous_post_without_csrf_token(user_factory):
    """``POST /api/auth/login/`` must be CSRF-protected exactly like the HTML login view.

    ``APIView.as_view()`` is ``csrf_exempt`` at the Django level, and DRF's
    ``SessionAuthentication`` only calls ``enforce_csrf()`` for a request that *already* carries
    an authenticated session — an anonymous login POST would otherwise never be checked at all.
    Regression test for the login-CSRF gap the ``csrf_protect`` decorator on ``LoginAPIView``
    closes (design.md "Security notes" claims the login form is CSRF-protected; without this,
    that was only true for the HTML view).
    """
    user = user_factory()
    csrf_client = APIClient(enforce_csrf_checks=True)

    response = csrf_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )

    assert response.status_code == 403
    assert get_user(csrf_client).is_anonymous


def test_api_login_succeeds_with_valid_csrf_token(user_factory):
    user = user_factory()
    csrf_client = APIClient(enforce_csrf_checks=True)
    # Any view rendering {% csrf_token %} sets the csrftoken cookie via get_token() — the HTML
    # login page already does this, so it doubles as the CSRF-cookie bootstrap here too.
    csrf_client.get("/accounts/login/")
    csrf_token = csrf_client.cookies["csrftoken"].value

    response = csrf_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 200
    assert get_user(csrf_client).is_authenticated


def test_login_and_password_change_mask_sensitive_post_parameters(user_factory):
    """API mirror of ``test_security.test_password_not_in_logs``, for the two views that carry
    passwords in their POST bodies.

    Django's ``LoginView``/``PasswordChangeView`` get ``sensitive_post_parameters()`` for free;
    DRF's ``APIView`` does not, so ``LoginAPIView`` and ``PasswordChangeAPIView`` apply it
    explicitly (``accounts/api.py``). Without it, an unhandled exception in either view would put
    the plaintext password (and ``old_password``/``new_password``) into whatever consumes
    ``SafeExceptionReporterFilter`` output — the DEBUG page, ``AdminEmailHandler``, or the
    ``django.request`` log record.
    """
    from django.views.debug import SafeExceptionReporterFilter

    user = user_factory()
    client = APIClient()
    client.force_login(user)

    login_response = client.post(
        "/api/auth/login/",
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )
    login_masked = SafeExceptionReporterFilter().get_post_parameters(login_response.wsgi_request)
    assert DEFAULT_TEST_PASSWORD not in login_masked.get("password", "")

    change_response = client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )
    change_masked = SafeExceptionReporterFilter().get_post_parameters(change_response.wsgi_request)
    assert DEFAULT_TEST_PASSWORD not in change_masked.get("old_password", "")
    assert "BrandNewPassw0rd!" not in change_masked.get("new_password", "")


def test_api_password_change_rejects_expired_temp_password(user_factory):
    """An expired temp password must not be usable as ``old_password`` to clear its own expiry.

    Regression test for the gap TempPasswordAwareBackend does not reach: this endpoint never
    calls authenticate(), so validate_old_password needs its own temp_password_expired() check
    (accounts/serializers.py) or a token holder can permanently re-enable a dead credential with
    no admin involvement (design.md step 5).
    """
    from datetime import timedelta

    from django.utils import timezone

    user = user_factory(password="StillCorrectPassw0rd!")
    user.must_change_password = True
    user.temp_password_expires_at = timezone.now() - timedelta(days=1)
    user.save(update_fields=["must_change_password", "temp_password_expires_at"])
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.post(
        "/api/auth/password/change/",
        {"old_password": "StillCorrectPassw0rd!", "new_password": "BrandNewPassw0rd!"},
    )

    assert response.status_code == 400
    assert "old_password" in response.data
    user.refresh_from_db()
    assert user.must_change_password is True
    assert user.check_password("StillCorrectPassw0rd!") is True


def test_password_change_revokes_existing_tokens(authenticated_client, user_factory):
    """A stolen or leaked token must not survive the password change meant to end it.

    Mirrors the session-cycling guarantee design.md already requires for sessions ("otherwise a
    stolen session survives the very reset that was meant to end it") — 01.7 is what turned
    tokens on, so the same rule has to extend to them.
    """
    user = get_user(authenticated_client)
    old_token = Token.objects.create(user=user)

    response = authenticated_client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )
    assert response.status_code == 204

    stale_client = APIClient()
    stale_client.credentials(HTTP_AUTHORIZATION=f"Token {old_token.key}")
    stale_response = stale_client.get("/api/auth/me/")

    # 403, not 401: get_authenticate_header() consults get_authenticators()[0], which is
    # SessionAuthentication and returns None, so DRF converts NotAuthenticated to 403 for every
    # rejected request regardless of which authenticator rejected it — see
    # test_me_requires_auth for the same nuance.
    assert stale_response.status_code == 403
    assert not Token.objects.filter(pk=old_token.pk).exists()


def test_token_auth_password_change_exempted(user_factory):
    """The one endpoint that can clear ``must_change_password`` must stay reachable, or a
    forced-reset token client has no way out (design.md, "The middleware").
    """
    user = user_factory(must_change_password=True)
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )

    assert response.status_code == 204


def test_forced_change_user_can_still_log_out_via_api_with_token(user_factory):
    """A must_change_password=True user must not be locked to exactly one legal API request.

    The HTML LogoutView is exempted from the equivalent middleware check for the same reason
    (design.md, "The middleware") — a forced-reset user must always be able to leave.
    LogoutAPIView's permission override closes this for a token client.
    """
    user = user_factory(must_change_password=True)
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.post("/api/auth/logout/")

    assert response.status_code == 204


def test_forced_change_user_can_still_log_out_via_api_with_session(user_factory):
    """Same guarantee as above, for a session-authenticated client.

    LogoutAPIView's permission override alone is not enough here: ForcePasswordChangeMiddleware
    runs before DRF permissions, so a session-authenticated request needs
    ``accounts_api:logout`` in the middleware's own exemption set too
    (accounts.middleware.api_logout_path), or it never reaches the permission at all.
    """
    user = user_factory(must_change_password=True)
    client = APIClient()
    client.force_login(user)

    response = client.post("/api/auth/logout/")

    assert response.status_code == 204


def test_token_authenticated_password_change_does_not_create_session_row(user_factory):
    """update_session_auth_hash must not run for a sessionless (token-only) request.

    It calls request.session.cycle_key() unconditionally, which on a request with no session
    cookie at all creates a brand-new, empty session row that nothing will ever authenticate
    with again — living for SESSION_COOKIE_AGE (one year) for no benefit.
    """
    from django.contrib.sessions.models import Session

    user = user_factory(must_change_password=True)
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    assert Session.objects.count() == 0

    response = client.post(
        "/api/auth/password/change/",
        {"old_password": DEFAULT_TEST_PASSWORD, "new_password": "BrandNewPassw0rd!"},
    )

    assert response.status_code == 204
    assert Session.objects.count() == 0


def test_forced_change_token_user_blocked_from_schema_and_docs(user_factory):
    """``/api/schema/`` and ``/api/docs/`` bypass ``DEFAULT_PERMISSION_CLASSES`` entirely.

    ``SpectacularAPIView``/the docs view set ``permission_classes = SERVE_PERMISSIONS`` directly,
    which *replaces* rather than extends the project-wide default list — so
    ``ForcePasswordChangeAPIPermission`` has to be listed there too
    (``config/settings/base.py``), or these two endpoints become the only ones in the project
    where a ``must_change_password=True`` token holder gets unrestricted access.

    Only a token client exercises this: a session-authenticated equivalent never reaches either
    view at all, because ``ForcePasswordChangeMiddleware`` already 403s it before DRF's
    permission classes run (see ``test_api_returns_403_not_redirect``).
    """
    user = user_factory(must_change_password=True)
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    schema_response = client.get("/api/schema/")
    docs_response = client.get("/api/docs/")

    assert schema_response.status_code == 403
    assert docs_response.status_code == 403
