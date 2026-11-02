"""Rate limiting (10.5 — ``Plan/10-Security-And-Deployment/test-plan.md``).

Login throttling itself (task 01.8) is exhaustively covered in ``accounts/tests/test_security.py``
— this file covers the endpoints 10.5 adds on top: password change, admin actions, the JSON
importer, and the global authenticated default. Each test below drives its endpoint through
real HTTP requests rather than calling the throttle helpers directly, so a wiring mistake (the
scope/rate never actually reaching the view) fails here exactly like it would in production.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(user_factory) -> Client:
    user = user_factory(username="throttlestaff", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    return client


def test_login_throttled(client, user_factory):
    """Smoke test for the location this test-plan names — the exhaustive matrix (all three
    endpoints, the shared bucket, the reset-on-success and per-IP-not-per-user fixes) lives in
    ``accounts/tests/test_security.py``.
    """
    user = user_factory()

    for _ in range(5):
        response = client.post(
            reverse("accounts:login"), {"username": user.username, "password": "wrong"}
        )
        assert response.status_code == 200

    sixth = client.post(reverse("accounts:login"), {"username": user.username, "password": "wrong"})
    assert sixth.status_code == 429


def test_password_change_throttled(authenticated_client):
    """Shared bucket, 5/min, between ``PasswordChangeAPIView`` and the HTML
    ``ForcedAwarePasswordChangeView`` (``accounts.throttling.PASSWORD_CHANGE_THROTTLE_SCOPE``).
    Every POST counts toward the bucket regardless of whether the body is valid — DRF's own
    throttle check runs in ``initial()``, before the view method (and so before serializer
    validation) ever runs.
    """
    url = reverse("accounts_api:password-change")

    for _ in range(5):
        response = authenticated_client.post(url, {}, format="json")
        assert response.status_code != 429

    sixth = authenticated_client.post(url, {}, format="json")
    assert sixth.status_code == 429


def test_password_change_shares_one_bucket_between_html_and_api(authenticated_client):
    """The same 5/min bucket backs both surfaces (``accounts.throttling
    .PASSWORD_CHANGE_THROTTLE_SCOPE``'s docstring) — exhausting it via the API must throttle
    the HTML view too, not grant it a separate budget of its own.
    """
    api_url = reverse("accounts_api:password-change")
    for _ in range(5):
        assert authenticated_client.post(api_url, {}, format="json").status_code != 429

    html_response = authenticated_client.post(
        reverse("accounts:password_change"),
        {"old_password": "x", "new_password1": "y", "new_password2": "y"},
    )
    assert html_response.status_code == 429


def test_password_change_bucket_survives_interleaved_html_and_api_calls_over_time(
    authenticated_client, monkeypatch
):
    """Task 10 review, blocking finding: the shared ``password_change`` bucket used to corrupt
    when both surfaces wrote to it, because ``PasswordChangeAPIView`` ran DRF's
    ``ScopedRateThrottle`` (newest-first, tail-pruned history) against the same cache key the
    HTML view's ``check_rate_limit`` writes with the opposite (append-at-tail) ordering. Once
    both had written, DRF's tail-only prune could stop at a not-yet-expired entry and never
    reach genuinely stale ones earlier in the list, refusing a request whose *real* window count
    was under the configured rate.

    Both surfaces now call ``check_rate_limit`` directly, so there is only one algorithm to go
    wrong — but this test pins the actual repro from the review (3/min, interleaved API/HTML
    calls with real gaps) rather than trusting that by inspection:

    ``t=0`` API (allowed), ``t=50`` API (allowed), ``t=55`` HTML (allowed), ``t=70`` API — at
    ``t=70`` only the ``t=50``/``t=55`` requests are still inside the 60s window (two live
    requests under a rate of three), so this fourth call must be allowed, not refused.
    """
    monkeypatch.setattr("accounts.throttling.PASSWORD_CHANGE_THROTTLE_RATE", "3/min")
    monkeypatch.setattr("accounts.views.PASSWORD_CHANGE_THROTTLE_RATE", "3/min")

    current_time = 0.0
    monkeypatch.setattr("core.services.ratelimit.time.time", lambda: current_time)

    api_url = reverse("accounts_api:password-change")
    html_body = {"old_password": "x", "new_password1": "y", "new_password2": "y"}

    current_time = 0.0
    assert authenticated_client.post(api_url, {}, format="json").status_code != 429

    current_time = 50.0
    assert authenticated_client.post(api_url, {}, format="json").status_code != 429

    current_time = 55.0
    html_response = authenticated_client.post(reverse("accounts:password_change"), html_body)
    assert html_response.status_code != 429

    current_time = 70.0
    fourth = authenticated_client.post(api_url, {}, format="json")
    assert fourth.status_code != 429, (
        "false 429 at t=70: only t=50/t=55 are inside the 60s window, well under the 3/min rate"
    )


def test_admin_actions_throttled(staff_client, user_factory, monkeypatch):
    """``accounts.admin``'s account-mutating actions (grant/revoke admin here) share one
    30/min bucket per staff user (``core.services.ratelimit.ADMIN_ACTION_THROTTLE_SCOPE``).
    Exercised well under 30 real requests by monkeypatching the rate down, the same technique
    ``test_global_authenticated_throttle`` below uses, rather than actually sending 31 requests.

    Patches ``accounts.admin.ADMIN_ACTION_THROTTLE_RATE`` specifically, not
    ``core.services.ratelimit``'s copy: ``accounts/admin.py``'s ``from ... import
    ADMIN_ACTION_THROTTLE_RATE`` binds its own name to the string at import time, so patching
    the origin module's attribute afterward would not be seen by the code path this test
    actually exercises.
    """
    monkeypatch.setattr("accounts.admin.ADMIN_ACTION_THROTTLE_RATE", "2/min")
    target = user_factory(username="throttletarget", is_staff=True)
    url = reverse("admin:accounts_user_changelist")
    body = {"action": "grant_admin", "_selected_action": [str(target.pk)]}

    for _ in range(2):
        response = staff_client.post(url, body)
        assert response.status_code != 429

    third = staff_client.post(url, body)
    assert third.status_code == 429


def test_import_throttled(staff_client, monkeypatch):
    """The bulk JSON importer (``core.admin.import_json_view``), 5/hour per staff user —
    counted on every POST regardless of payload validity, since the throttle check runs before
    the upload form is even built. See ``test_admin_actions_throttled`` above for why this
    patches ``core.admin.IMPORT_THROTTLE_RATE`` rather than ``core.services.ratelimit``'s copy.
    """
    monkeypatch.setattr("core.admin.IMPORT_THROTTLE_RATE", "2/hour")
    url = reverse("admin:core_import_json")

    for _ in range(2):
        response = staff_client.post(url, {})
        assert response.status_code != 429

    third = staff_client.post(url, {})
    assert third.status_code == 429


def test_global_authenticated_throttle(authenticated_client, monkeypatch):
    """Every DRF endpoint that declares no throttle of its own — ``GET /api/auth/me/`` here,
    which has none — gets the 1000/hour default (``UserRateThrottle``) for free. Verified by
    monkeypatching the *rate* down to 2/hour rather than sending 1001 real requests: DRF's
    ``SimpleRateThrottle.THROTTLE_RATES`` is one shared dict every scoped/keyed throttle class
    reads from, mutated in place here (not reassigned) so the change is visible without
    fighting DRF's own settings-reload caching, and reverted automatically by ``monkeypatch``.
    """
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "user", "2/hour")
    url = reverse("accounts_api:me")

    for _ in range(2):
        response = authenticated_client.get(url)
        assert response.status_code == 200

    third = authenticated_client.get(url)
    assert third.status_code == 429


def test_throttle_returns_429_with_retry_after(client, user_factory):
    """The API login path's own 429 (DRF's built-in ``Throttled`` exception handling) carries
    ``Retry-After`` too — the HTML login path's equivalent is pinned separately in
    ``accounts/tests/test_security.py``, and ``/admin/login/``'s in
    ``accounts/tests/test_security.py::test_admin_login_throttled_response_has_retry_after``.
    """
    from rest_framework.test import APIClient

    api_client = APIClient()
    user = user_factory()

    for _ in range(5):
        response = api_client.post(
            "/api/auth/login/", {"username": user.username, "password": "wrong"}
        )
        assert response.status_code == 400

    sixth = api_client.post("/api/auth/login/", {"username": user.username, "password": "wrong"})

    assert sixth.status_code == 429
    assert "Retry-After" in sixth
    assert int(sixth["Retry-After"]) > 0


def test_admin_actions_and_import_use_different_scopes(staff_client, user_factory, monkeypatch):
    """Non-vacuous: exhausting the import bucket must not also throttle an ordinary admin
    action for the same staff user — proves the two 10.5 scopes are genuinely independent
    buckets, not accidentally sharing one cache key.
    """
    monkeypatch.setattr("core.admin.IMPORT_THROTTLE_RATE", "1/hour")
    import_url = reverse("admin:core_import_json")
    assert staff_client.post(import_url, {}).status_code != 429
    assert staff_client.post(import_url, {}).status_code == 429

    target = user_factory(username="unaffectedtarget", is_staff=True)
    changelist_url = reverse("admin:accounts_user_changelist")
    body = {"action": "grant_admin", "_selected_action": [str(target.pk)]}
    assert staff_client.post(changelist_url, body).status_code != 429
