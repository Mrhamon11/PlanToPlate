"""Login/logout flow tests (subtask 01.6) and the session-configuration tests from 01.5 that
needed a real request/response cycle rather than the login view itself.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.models import Session
from django.urls import reverse
from django.utils import timezone

from conftest import DEFAULT_TEST_PASSWORD

pytestmark = pytest.mark.django_db


def test_login_success_redirects_to_home(client, user_factory):
    user = user_factory()

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )

    assert response.status_code == 302
    assert response.url == reverse("core:home")
    assert get_user(client).is_authenticated


def test_login_wrong_password_fails(client, user_factory):
    user = user_factory()

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "not-the-real-password"},
    )

    assert response.status_code == 200
    assert response.context["form"].errors
    assert get_user(client).is_anonymous


def test_login_nonexistent_user_same_message(client, user_factory):
    """The error text is byte-identical to the wrong-password case — a different message per
    case is a user-enumeration oracle (design.md, "Edge cases").
    """
    user = user_factory()

    wrong_password_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "not-the-real-password"},
    )
    nonexistent_user_response = client.post(
        reverse("accounts:login"),
        {"username": "no-such-user-exists", "password": "not-the-real-password"},
    )

    assert (
        wrong_password_response.context["form"].errors
        == nonexistent_user_response.context["form"].errors
    )


def test_logout_requires_post(client, user_factory):
    """A GET logout is CSRF-triggerable from an ``<img>`` tag on any site."""
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("accounts:logout"))

    assert response.status_code == 405
    assert get_user(client).is_authenticated


def test_logout_clears_session(client, user_factory):
    user = user_factory()
    client.force_login(user)
    assert get_user(client).is_authenticated

    response = client.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert get_user(client).is_anonymous


def test_session_survives_browser_close(client, user_factory):
    user = user_factory()
    client.force_login(user)

    response = client.get("/healthz/")

    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["max-age"] != ""
    assert int(cookie["max-age"]) == settings.SESSION_COOKIE_AGE


def test_session_is_rolling(client, user_factory, monkeypatch):
    user = user_factory()
    client.force_login(user)

    client.get("/healthz/")
    session_key = client.session.session_key
    first_expiry = Session.objects.get(session_key=session_key).expire_date

    later = timezone.now() + timedelta(days=10)
    monkeypatch.setattr(timezone, "now", lambda: later)

    client.get("/healthz/")
    second_expiry = Session.objects.get(session_key=session_key).expire_date

    assert second_expiry > first_expiry


def test_session_cookie_httponly_and_samesite(client, user_factory):
    user = user_factory()
    client.force_login(user)

    response = client.get("/healthz/")

    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert bool(cookie["httponly"]) is True
    assert cookie["samesite"] == "Lax"
