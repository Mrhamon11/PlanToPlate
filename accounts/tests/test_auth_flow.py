"""Login-flow tests (subtask 01.6) are not here yet — there is no login view until then.

Only the session-configuration tests from the test plan that don't require the login view
land in this iteration: ``test_session_survives_browser_close``, ``test_session_is_rolling``,
and ``test_session_cookie_httponly_and_samesite``. They authenticate via
``Client.force_login`` and exercise a real request/response cycle so
``SessionMiddleware.process_response`` actually writes the cookie from
``SESSION_COOKIE_*`` settings — ``force_login`` alone stamps a session cookie with hardcoded
defaults that ignore those settings entirely.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone

pytestmark = pytest.mark.django_db


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
