"""Security tests, including the login throttle (subtask 01.8)."""

import logging
import time
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import base_user as base_user_module
from django.contrib.auth import get_user
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import NoReverseMatch, URLResolver, get_resolver, reverse
from rest_framework.throttling import ScopedRateThrottle

from accounts.api import LoginAPIView
from accounts.forms import TempPasswordAwareAuthenticationForm
from accounts.throttling import LOGIN_THROTTLE_SCOPE, _LoginThrottleTarget
from accounts.views import TempPasswordAwareLoginView, ThrottledLoginMixin
from conftest import DEFAULT_TEST_PASSWORD

pytestmark = pytest.mark.django_db


def _all_pattern_strings(patterns) -> list[str]:
    """Flatten a URLconf into every route string and name, recursing into included urlconfs.

    A shallow scan of ``get_resolver().url_patterns`` only sees top-level entries like
    ``accounts/`` — it would never notice a ``signup/`` path added inside ``accounts.urls``.
    Walking into every ``URLResolver`` is what makes the scan actually catch that.
    """
    found = []
    for pattern in patterns:
        found.append(str(pattern.pattern))
        if getattr(pattern, "name", None):
            found.append(pattern.name)
        if isinstance(pattern, URLResolver):
            found.extend(_all_pattern_strings(pattern.url_patterns))
    return found


def test_password_min_length_enforced(user_factory):
    user = user_factory()

    with pytest.raises(ValidationError):
        validate_password("Abcdefg1!", user=user)  # 9 characters, one under the minimum


def test_no_registration_url_exists():
    """design.md is explicit: no signup view, no signup URL, accounts are admin-provisioned.

    Guards against both a self-registration route being added directly and against 01.6 later
    wiring up ``django.contrib.auth.urls`` wholesale, which ships a registration/password-reset
    route set alongside the login/logout views this task actually wants.
    """
    signup_route_names = [
        "signup",
        "register",
        "registration",
        "accounts:signup",
        "accounts:register",
    ]
    for name in signup_route_names:
        with pytest.raises(NoReverseMatch):
            reverse(name)

    all_patterns = _all_pattern_strings(get_resolver().url_patterns)
    combined = " ".join(all_patterns).lower()
    assert "signup" not in combined
    assert "register" not in combined


def test_password_not_in_logs(client, user_factory, caplog):
    plain_password = "correct-horse-battery-staple"
    user = user_factory(password=plain_password)

    with caplog.at_level(logging.DEBUG):
        client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": plain_password},
        )
        client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "definitely-the-wrong-password"},
        )

    for record in caplog.records:
        assert plain_password not in record.getMessage()
        assert "definitely-the-wrong-password" not in record.getMessage()


def test_login_throttled_after_five_attempts(client, user_factory):
    """The sixth login POST from the same IP inside the window is throttled — regardless of
    whether the credentials submitted are right or wrong, since the limit is on attempts, not
    on failures (design.md, "Login throttling").
    """
    user = user_factory()

    for _ in range(5):
        response = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
        )
        assert response.status_code == 200

    sixth_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "wrong-password"},
    )

    assert sixth_response.status_code == 429


def test_api_login_throttled_after_five_attempts(api_client, user_factory):
    """Same limit, same cache key/scope, on the API login path — design.md requires both."""
    user = user_factory()

    for _ in range(5):
        response = api_client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "wrong-password"},
        )
        assert response.status_code == 400

    sixth_response = api_client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "wrong-password"},
    )

    assert sixth_response.status_code == 429


def test_admin_login_throttled_after_five_attempts(client, user_factory):
    """``/admin/login/`` is a third credential-accepting endpoint — found completely
    unthrottled in iteration 1's security review (30 wrong-password POSTs, all 200, zero 429).
    Fronts the worst account in the system: ``bootstrap_admin`` creates a superuser at the
    guessable default username ``admin``.
    """
    user_factory(username="admin", is_staff=True, is_superuser=True)

    for _ in range(5):
        response = client.post(
            "/admin/login/",
            {"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 200

    sixth_response = client.post(
        "/admin/login/",
        {"username": "admin", "password": "wrong-password"},
    )

    assert sixth_response.status_code == 429


def test_all_three_login_endpoints_share_one_throttle_budget(client, api_client, user_factory):
    """The HTML login, the API login, and ``/admin/login/`` combined share one 5/min bucket —
    an attacker cannot triple their attempt budget by splitting attempts across all three.
    Asserted in prose by both ``accounts/views.py`` and ``accounts/api.py``; nothing exercised
    it until now.
    """
    user_factory(username="admin", is_staff=True, is_superuser=True)

    for _ in range(2):
        response = client.post(
            reverse("accounts:login"),
            {"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 200

    for _ in range(2):
        response = api_client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 400

    fifth_response = client.post(
        "/admin/login/",
        {"username": "admin", "password": "wrong-password"},
    )
    assert fifth_response.status_code == 200

    sixth_response = client.post(
        "/admin/login/",
        {"username": "admin", "password": "wrong-password"},
    )

    assert sixth_response.status_code == 429


def test_the_login_throttle_scope_lives_in_exactly_one_place():
    """The shared bucket the test above proves is held together by one constant, and by no
    per-view copy of it that could drift.

    ``ThrottledLoginMixin`` used to carry ``throttle_scope = "login"``, which nothing read —
    ``check_login_throttle`` passes its own target — so it could be changed to any value at all
    with the whole suite still green, while reading exactly like the knob that configures this
    view's throttle. Only the two attributes asserted here are load-bearing: DRF reads
    ``LoginAPIView.throttle_scope``, and ``check_login_throttle`` reads
    ``_LoginThrottleTarget.throttle_scope``.
    """
    assert _LoginThrottleTarget.throttle_scope == LOGIN_THROTTLE_SCOPE
    assert LoginAPIView.throttle_scope == LOGIN_THROTTLE_SCOPE
    assert LOGIN_THROTTLE_SCOPE in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

    for view in (ThrottledLoginMixin, TempPasswordAwareLoginView):
        assert not hasattr(view, "throttle_scope"), (
            f"{view.__name__}.throttle_scope is inert — the Django-side login paths take their "
            "scope from accounts.throttling._LoginThrottleTarget. Make it load-bearing or "
            "remove it; do not leave a knob that silently does nothing."
        )


def test_throttle_survives_x_forwarded_for_rotation_when_num_proxies_configured(
    client, user_factory, settings
):
    """Reproduces and closes iteration 1's blocking finding: with ``NUM_PROXIES`` unset (the
    dev/test default, matching pre-fix ``base.py``), DRF's ``get_ident`` keys the throttle on
    the *entire* client-supplied ``X-Forwarded-For`` header — rotating it on every request
    bypassed the throttle completely (20 wrong-password POSTs, zero 429, measured live in
    review). ``config/settings/prod.py`` sets ``NUM_PROXIES = 1`` so DRF instead trusts only
    the single hop Caddy itself appends (the last comma-separated entry), which a client cannot
    forge away. Simulated here with ``override_settings`` rather than importing ``prod.py``
    wholesale, since this test only needs to pin the throttling *mechanism*, not prod's full
    settings surface (that surface is covered separately in ``config/tests/test_settings.py``).

    The trailing hop is held constant across every request — exactly what Caddy's own append
    behaviour produces for a fixed real client — while the attacker-controlled prefix rotates;
    NUM_PROXIES=1 must still throttle on the sixth attempt.
    """
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    user = user_factory()

    for i in range(5):
        response = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
            HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.1",
        )
        assert response.status_code == 200

    sixth_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "wrong-password"},
        HTTP_X_FORWARDED_FOR="10.0.0.99, 203.0.113.1",
    )

    assert sixth_response.status_code == 429


def test_throttle_window_is_approximately_one_minute(client, user_factory, monkeypatch):
    """Pins the throttle's *window*, not just its count. Mutation-verified during review:
    changing ``"login": "5/min"`` to ``"5/day"`` in ``config/settings/base.py`` left the whole
    suite green — nothing before this asserted anything about the window's actual duration.
    ``test_throttle_does_not_lock_the_account`` simulates the window elapsing by clearing the
    cache directly, which proves clearing the cache clears the throttle and nothing about how
    long a real window is.

    Advances ``ScopedRateThrottle``'s own clock rather than sleeping for real or clearing the
    cache: the throttle's history-eviction check compares ``self.timer()`` against stored
    timestamps, so patching the clock forward is what makes "a minute has passed" true from the
    code's own perspective, deterministically and without a real 61-second sleep in the suite.
    """
    user = user_factory()
    real_timer = time.time
    offset = 0.0

    def fake_timer() -> float:
        return real_timer() + offset

    monkeypatch.setattr(ScopedRateThrottle, "timer", staticmethod(fake_timer))

    for _ in range(5):
        response = client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
        )
        assert response.status_code == 200

    throttled_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "wrong-password"},
    )
    assert throttled_response.status_code == 429

    # 5 seconds later the window has not elapsed — a rate mutated to something far shorter
    # than a minute (e.g. "5/sec") would incorrectly let this one through.
    offset = 5.0
    still_throttled_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "wrong-password"},
    )
    assert still_throttled_response.status_code == 429

    # 61 seconds later the window has elapsed and the real password works again — a rate
    # mutated to something far longer than a minute (e.g. "5/day") would keep this 429.
    offset = 61.0
    response_after_window = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )

    assert response_after_window.status_code == 302
    assert get_user(client).is_authenticated


def test_throttle_does_not_lock_the_account(client, user_factory):
    """Design.md is explicit: the throttle slows an attacker down, it must never lock the
    account out. Once the window has elapsed, the real password still works — simulated here
    by clearing the throttle's cache directly rather than sleeping a minute in the suite.
    """
    user = user_factory()

    for _ in range(5):
        client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "wrong-password"},
        )
    throttled_response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )
    assert throttled_response.status_code == 429

    cache.clear()

    response_after_window = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": DEFAULT_TEST_PASSWORD},
    )

    assert response_after_window.status_code == 302
    assert get_user(client).is_authenticated


def _login_form_hash_operation_count(username: str, password: str) -> int:
    """Runs the login form's ``clean()`` once and counts PBKDF2-style hash operations.

    ``django.contrib.auth.base_user`` imports ``check_password``/``make_password`` from
    ``django.contrib.auth.hashers`` directly into its own module namespace, and
    ``AbstractBaseUser.check_password()``/``set_password()`` call those imported names — so
    patching them there (rather than at their original ``hashers`` location) is what actually
    intercepts every hash operation ``authenticate()`` and the form's own re-check perform,
    regardless of which ``PASSWORD_HASHERS`` entry is configured. Counting calls rather than
    timing them is deterministic and needs no ``override_settings`` to be measurable, unlike
    the flaky, PBKDF2-only timing version this replaces (measured during review: ~13% failure
    rate across 15 runs, both directions, against a 1.6x tolerance that ordinary jitter alone
    already exceeded — and it made up roughly 75% of the whole suite's wall-clock time).
    """
    request = RequestFactory().post("/accounts/login/")
    count = 0
    real_check_password = base_user_module.check_password
    real_make_password = base_user_module.make_password

    def counting_check_password(*args, **kwargs):
        nonlocal count
        count += 1
        return real_check_password(*args, **kwargs)

    def counting_make_password(*args, **kwargs):
        nonlocal count
        count += 1
        return real_make_password(*args, **kwargs)

    with (
        patch.object(base_user_module, "check_password", counting_check_password),
        patch.object(base_user_module, "make_password", counting_make_password),
    ):
        form = TempPasswordAwareAuthenticationForm(
            request, data={"username": username, "password": password}
        )
        form.is_valid()

    return count


def test_wrong_password_and_nonexistent_user_perform_the_same_hash_operation_count(
    user_factory,
):
    """Pins the timing-equalisation property design.md relies on to keep login from being a
    user-enumeration oracle, by counting hash operations rather than timing them.

    Both branches must perform exactly two hash operations today: ``authenticate()`` itself
    (one, real or dummy, per Django's own #20760 equalisation) followed by this form's own
    re-check for the temp-password-expiry message (one more, real or dummy — see
    ``accounts.forms``' module docstring). The regression this guards against drops the form's
    own dummy hash on the nonexistent-user branch (removing the ``set_password()`` call at
    ``accounts/forms.py``'s ``DoesNotExist`` handler), which would drop that branch's count from
    two to one while the existing-user branch stays at two — caught here as a hard count
    mismatch rather than a probabilistic timing ratio. Verified by temporarily deleting that
    line during review: this test fails (``2 != 1``) exactly as intended.
    """
    user = user_factory()

    existing_user_count = _login_form_hash_operation_count(user.username, "wrong-password")
    nonexistent_user_count = _login_form_hash_operation_count(
        "definitely-does-not-exist", "wrong-password"
    )

    assert existing_user_count == 2
    assert nonexistent_user_count == 2
