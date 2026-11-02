"""Security headers and settings (10.3 — ``Plan/10-Security-And-Deployment/test-plan.md``).

Reuses ``config.tests.test_settings``'s subprocess-import helper rather than duplicating it:
by the time pytest runs, ``config.settings.test`` is already cached in ``sys.modules``, so a
fresh subprocess is the only way to see what importing ``config.settings.prod`` actually
produces — see that module's own docstring.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from config.tests.test_settings import _import_settings_module

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# A random, high-entropy key -- unlike the "x" * 50 literal ``config.tests.test_settings`` uses
# for plain import checks, ``check --deploy`` itself flags a low-entropy SECRET_KEY
# (security.W009: "less than 5 unique characters"), so a fixed repeated-character string would
# make this specific test always see one warning no matter what else is fixed.
_REAL_SECRET_KEY = secrets.token_urlsafe(64)


def _prod_settings(**extra_env: str) -> dict:
    env = {"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com", **extra_env}
    result = _import_settings_module("config.settings.prod", env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_deploy_check_clean(tmp_path):
    """``manage.py check --deploy`` under prod settings returns zero warnings or errors —
    the task-10 Definition of Done, not merely Django's own ``security.W*`` checks: anything
    else registered in the project (drf-spectacular's schema sanity check included) must also
    be clean, since a warning ignored here is a warning nobody will ever look at again.

    This subprocess runs ``manage.py`` directly (not ``_import_settings_module``'s bare
    ``importlib.import_module``), which triggers a real ``django.setup()`` — the point where
    ``LOGGING``'s rotating file handlers are actually instantiated (10.15) and
    ``FileBasedCache``'s directory can be touched. ``CACHE_DIR``/``LOG_DIR`` are pointed at
    ``tmp_path`` here for the same reason ``_import_settings_module``'s ``isolate_dirs``
    defaults to ``True``: left unset, this specific test would otherwise leave a real
    ``cache/`` directory and populated ``logs/`` directory at the repo root on every run.
    """
    process_env = {
        **os.environ,
        "SECRET_KEY": _REAL_SECRET_KEY,
        "ALLOWED_HOSTS": "example.com",
        "CSRF_TRUSTED_ORIGINS": "https://example.com",
        "CACHE_DIR": str(tmp_path / "cache"),
        "LOG_DIR": str(tmp_path / "logs"),
        "DJANGO_ENV_FILE": "/nonexistent/plantoplate-test.env",
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    }

    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=str(BASE_DIR),
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "System check identified no issues" in result.stdout, result.stdout + result.stderr


def test_hsts_configured():
    data = _prod_settings()

    assert data["SECURE_HSTS_SECONDS"] == 60 * 60 * 24 * 365
    assert data["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert data["SECURE_HSTS_PRELOAD"] is True


def test_ssl_redirect_enabled():
    data = _prod_settings()

    assert data["SECURE_SSL_REDIRECT"] is True


def test_cookies_secure_and_httponly():
    data = _prod_settings()

    assert data["SESSION_COOKIE_SECURE"] is True
    assert data["CSRF_COOKIE_SECURE"] is True
    # HttpOnly is set in base.py (shared by every environment), not prod-only — a session
    # cookie a script can read is a session cookie XSS can steal.
    assert data["SESSION_COOKIE_HTTPONLY"] is True


def test_x_frame_options_deny():
    data = _prod_settings()

    assert data["X_FRAME_OPTIONS"] == "DENY"


def test_content_type_nosniff():
    data = _prod_settings()

    assert data["SECURE_CONTENT_TYPE_NOSNIFF"] is True


def test_referrer_policy():
    data = _prod_settings()

    assert data["SECURE_REFERRER_POLICY"] == "same-origin"


def test_allowed_hosts_not_wildcard():
    """``["*"]`` in production must fail outright: Django's own ``check --deploy`` only warns
    on an *empty* ``ALLOWED_HOSTS`` (``security.W020``), never on a wildcard, so nothing else
    catches this exact misconfiguration — the one a rushed first deploy reaches for. Importing
    ``config.settings.prod`` with a wildcard must raise, not silently accept it.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "*"},
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "ALLOWED_HOSTS" in result.stderr


def test_allowed_hosts_real_hostname_accepted():
    """Non-vacuous: a real hostname must still import cleanly — proves the guard above rejects
    only the wildcard, not ``ALLOWED_HOSTS`` in general.
    """
    data = _prod_settings()

    assert "example.com" in data["ALLOWED_HOSTS"]
    assert "*" not in data["ALLOWED_HOSTS"]


def test_debug_false_in_prod():
    data = _prod_settings()

    assert data["DEBUG"] is False
