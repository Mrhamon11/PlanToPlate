"""Login-throttle tests (subtask 01.8) are not here yet — they need the throttled login view
that lands in that subtask.
"""

import logging

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.urls import NoReverseMatch, URLResolver, get_resolver, reverse

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
