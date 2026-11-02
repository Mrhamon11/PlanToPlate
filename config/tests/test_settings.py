"""Assert the *configuration* is correct, not application behaviour.

Several of these tests re-import a settings module in a subprocess. That is necessary, not
decorative: by the time pytest is running, ``config.settings.test`` is already imported and
cached in ``sys.modules``, so re-importing ``base``/``dev``/``prod`` in-process would not
re-run the environment reads those modules do at import time (``SECRET_KEY = env("SECRET_KEY")``
and friends). A subprocess gets a fresh interpreter and a fresh environment.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connections

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Any file that cannot exist, used to make environ.Env.read_env() a guaranteed no-op so a
# developer's real .env never shadows what a test is deliberately unsetting.
NO_ENV_FILE = "/nonexistent/plantoplate-test.env"


def _import_settings_module(
    module_name: str,
    env: dict[str, str] | None = None,
    unset=(),
    isolate_dirs: bool = True,
):
    """Import ``module_name`` in a subprocess; return the completed process.

    On success, ``stdout`` is a JSON object of every uppercase name the module defines
    (non-JSON-serialisable values, like ``Path``, are stringified).

    ``isolate_dirs`` (default ``True``) points ``CACHE_DIR`` and ``LOG_DIR`` at a fresh
    temporary directory, unless ``env`` already sets one explicitly. Both settings default
    (in ``config.settings.prod``) to a path under this project's own ``BASE_DIR`` when unset,
    and both are actually created at import time — ``FileBasedCache``'s directory lazily on
    first use, and ``LOGGING``'s rotating file handlers eagerly, since a missing log directory
    must never crash a running deployment the first time something logs. Left unisolated, every
    test importing ``config.settings.prod`` without its own override would leave a stray
    ``cache/`` / ``logs/`` directory (the latter with real, if empty, log files) at the repo
    root (10.3's carried-forward finding, extended to ``LOG_DIR`` in 10.15 — the trigger for
    fixing both here rather than letting a second instance of the same problem stand). The two
    tests that specifically exercise the real default pass ``isolate_dirs=False`` and accept
    that one-time side effect deliberately.
    """
    process_env = os.environ.copy()
    for key in unset:
        process_env.pop(key, None)
    process_env.pop("DJANGO_SETTINGS_MODULE", None)
    process_env.setdefault("DJANGO_ENV_FILE", NO_ENV_FILE)
    process_env.update(env or {})

    with tempfile.TemporaryDirectory(prefix="plantoplate-settings-test-") as scratch_dir:
        if isolate_dirs:
            process_env.setdefault("CACHE_DIR", str(Path(scratch_dir) / "cache"))
            process_env.setdefault("LOG_DIR", str(Path(scratch_dir) / "logs"))

        script = (
            "import importlib, json\n"
            f"mod = importlib.import_module({module_name!r})\n"
            "public = {k: v for k, v in vars(mod).items() if k.isupper()}\n"
            "print(json.dumps(public, default=str))\n"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=BASE_DIR,
            env=process_env,
            capture_output=True,
            text=True,
            check=False,
        )


def test_secret_key_required():
    result = _import_settings_module("config.settings.base", unset=["SECRET_KEY"])

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "SECRET_KEY" in result.stderr


def test_debug_false_in_prod():
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["DEBUG"] is False


def _base_sqlite_options() -> dict:
    """The OPTIONS block base.py attaches for a SQLite DATABASE_URL, read from base itself.

    Sourced from ``config.settings.base`` rather than ``django.conf.settings`` on purpose.
    The running suite uses ``config.settings.test``, which reuses base's ``SQLITE_OPTIONS``
    constant — but reading it back through ``django.conf.settings`` would assert only that
    test settings are self-consistent. Going to base directly keeps this test pointed at the
    production configuration, the only one that ever serves concurrent writers.
    """
    result = _import_settings_module(
        "config.settings.base",
        env={"SECRET_KEY": "x" * 50, "DATABASE_URL": "sqlite:////tmp/plantoplate-pragma.sqlite3"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["DATABASES"]["default"]["OPTIONS"]


def test_sqlite_pragmas_applied(tmp_path, django_db_blocker):
    """The exact OPTIONS block from base.py, applied through Django's own SQLite backend,
    yields WAL.

    Goes through ``django.db.connections`` rather than a raw ``sqlite3.connect()`` — a raw
    connection only proves the pragma string is valid SQL, not that Django's backend actually
    forwards ``OPTIONS`` to the connection it opens. Registering a real, temporary, file-backed
    alias in ``settings.DATABASES`` and reading the pragmas back through a cursor on *that*
    alias is what makes this test fail if ``OPTIONS`` ever stops reaching the backend — e.g. the
    key gets renamed, or Django drops below 5.1 where ``transaction_mode`` doesn't exist.

    Uses the ``django_db_blocker`` fixture directly, rather than the ``django_db`` marker: the
    marker wraps the test in a ``TestCase`` whose ``databases`` allowlist is validated against
    ``settings.DATABASES`` *before* the test body runs, which is too early for an alias this
    test only registers at runtime. ``django_db_blocker.unblock()`` just lifts pytest-django's
    "no database access" guard for the duration of the block, with no such allowlist.
    """
    db_path = tmp_path / "pragma_check.sqlite3"
    options = _base_sqlite_options()
    assert options, "expected sqlite OPTIONS to be set for a sqlite DATABASE_URL"

    alias = "pragma_check"
    settings.DATABASES[alias] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(db_path),
        # timeout=0 forces busy_timeout to 0 on connect. sqlite3 otherwise defaults to
        # timeout=5.0, which sets busy_timeout=5000 on its own and would make the assertion
        # below pass even if the pragma were deleted from base.py.
        "OPTIONS": {**options, "timeout": 0},
        # ConnectionHandler.configure_settings() fills these defaults in, but only once, the
        # first time settings.DATABASES is read — long before this test adds an alias to it.
        # Supply them explicitly rather than relying on a setdefault() pass that already ran.
        "TIME_ZONE": None,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
    }
    try:
        with django_db_blocker.unblock():
            connection = connections[alias]
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0]
                cursor.execute("PRAGMA foreign_keys")
                foreign_keys = cursor.fetchone()[0]
                cursor.execute("PRAGMA busy_timeout")
                busy_timeout = cursor.fetchone()[0]
    finally:
        connections[alias].close()
        del connections[alias]
        del settings.DATABASES[alias]

    assert journal_mode == "wal"
    assert foreign_keys == 1
    assert busy_timeout == 5000
    assert options["transaction_mode"] == "IMMEDIATE"


def test_sqlite_options_skipped_for_postgres():
    result = _import_settings_module(
        "config.settings.base",
        env={
            "SECRET_KEY": "x" * 50,
            "DATABASE_URL": "postgres://user:pass@localhost:5432/dbname",
        },
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["DATABASES"]["default"]["ENGINE"].endswith("postgresql")
    assert "OPTIONS" not in data["DATABASES"]["default"]


def test_database_url_override(tmp_path):
    custom_path = tmp_path / "custom.sqlite3"
    result = _import_settings_module(
        "config.settings.base",
        env={"SECRET_KEY": "x" * 50, "DATABASE_URL": f"sqlite:///{custom_path}"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["DATABASES"]["default"]["NAME"] == str(custom_path)


def test_prod_security_flags():
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["SESSION_COOKIE_SECURE"] is True
    assert data["CSRF_COOKIE_SECURE"] is True
    assert data["SECURE_SSL_REDIRECT"] is True
    assert int(data["SECURE_HSTS_SECONDS"]) > 0
    # Without this, a container-internal healthcheck (no X-Forwarded-Proto, since it bypasses
    # Caddy) gets a 301 that never touches the database and reads as "healthy" to `curl -f`.
    assert data["SECURE_REDIRECT_EXEMPT"] == ["^healthz/$"]


def test_test_settings_force_sqlite_even_under_postgres_database_url():
    """config.settings.test must ignore DATABASE_URL entirely and always use in-memory SQLite.

    Reproduces the escape hatch a developer would use to verify Postgres portability
    (pointing DATABASE_URL at a real server, per MILESTONES.md) and confirms the test suite
    does not follow it there.
    """
    result = _import_settings_module(
        "config.settings.test",
        env={
            "SECRET_KEY": "x" * 50,
            "DATABASE_URL": "postgres://user:pass@localhost:5432/realdb",
        },
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["DATABASES"]["default"]["ENGINE"].endswith("sqlite3")
    assert data["DATABASES"]["default"]["NAME"] == ":memory:"


def test_drf_defaults_deny_by_default():
    """An endpoint that forgets its permission class must fail closed, not open.

    Asserted against the *resolved* ``api_settings`` rather than the raw dict: deleting the
    key from base.py restores DRF's ``AllowAny`` default silently, and a raw-dict assertion
    would only catch that as an incidental KeyError.
    """
    from rest_framework.permissions import AllowAny, IsAuthenticated
    from rest_framework.settings import api_settings

    from accounts.permissions import ForcePasswordChangeAPIPermission

    resolved = api_settings.DEFAULT_PERMISSION_CLASSES

    assert resolved == [IsAuthenticated, ForcePasswordChangeAPIPermission], resolved
    assert AllowAny not in resolved


def test_test_settings_pragmas_match_base():
    """test.py must keep *reusing* base's SQLITE_OPTIONS, not fall back to a local copy.

    test.py declares its own DATABASES so the suite can never follow DATABASE_URL to a real
    server, but it takes OPTIONS from base's constant. If someone re-inlines a literal pragma
    block there, this catches the moment it diverges.
    """
    assert settings.DATABASES["default"]["OPTIONS"] == _base_sqlite_options()


def test_drf_does_not_enable_basic_authentication():
    """DRF's built-in default is [SessionAuthentication, BasicAuthentication].

    Leaving that default in place would accept ``Authorization: Basic`` on every endpoint,
    unthrottled — a password-guessing oracle that bypasses the login view entirely. Asserted
    against the *resolved* ``api_settings`` rather than the raw dict, so deleting the key from
    base.py (which silently restores DRF's default) fails here too.
    """
    from rest_framework.authentication import BasicAuthentication, SessionAuthentication
    from rest_framework.settings import api_settings

    resolved = api_settings.DEFAULT_AUTHENTICATION_CLASSES

    assert BasicAuthentication not in resolved
    assert SessionAuthentication in resolved


def test_prod_sets_num_proxies_for_throttle_ident():
    """Without this, DRF's ``ScopedRateThrottle`` keys on the entire client-supplied
    ``X-Forwarded-For`` header rather than the single rightmost entry — reproduced live in
    review as a complete login-throttle bypass via a rotating header. (Caddy's own reverse_proxy
    already replaces, not appends to, that header by default — see the Caddyfile and
    ``config/settings/prod.py``'s own comments — so ``NUM_PROXIES=1`` is belt-and-braces, not
    the only thing standing between an attacker and this bypass.) Prod-only: under
    ``runserver`` with no proxy in front, ``NUM_PROXIES=1`` would trust the *last* entry of a
    header that is still entirely attacker-controlled, which is no improvement at all.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["REST_FRAMEWORK"]["NUM_PROXIES"] == 1


def test_base_and_test_settings_leave_num_proxies_unset():
    """dev/test must keep DRF's default (``REMOTE_ADDR``-only, no proxy hop trusted) — setting
    ``NUM_PROXIES`` outside of prod would trust a header nothing here actually strips or
    overwrites.
    """
    assert "NUM_PROXIES" not in settings.REST_FRAMEWORK


def test_prod_cache_is_shared_across_worker_processes():
    """``docker-entrypoint.sh`` starts gunicorn with ``--workers 2``. Django's unconfigured
    default, ``LocMemCache``, is per-process — reproduced in review as the login throttle
    silently enforcing 10/min instead of design.md's 5/min, with counters reset by any worker
    recycle. ``FileBasedCache`` needs no new dependency and no database table (unlike
    ``DatabaseCache``, which needs ``createcachetable`` — a data-mutating command outside this
    task's authorisation).
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert (
        data["CACHES"]["default"]["BACKEND"]
        == "django.core.cache.backends.filebased.FileBasedCache"
    )


def test_prod_cache_location_follows_cache_dir_env_var(tmp_path):
    """10.3 carried finding from task 01: only ``BACKEND`` was ever asserted, so hardcoding
    ``LOCATION`` to a fixed path (dropping the ``env("CACHE_DIR", default=...)`` read) would
    leave the whole suite green. Pinned here: setting ``CACHE_DIR`` must change ``LOCATION`` to
    exactly that path, not merely to *some* path under it.
    """
    custom_dir = tmp_path / "custom-cache"
    result = _import_settings_module(
        "config.settings.prod",
        env={
            "SECRET_KEY": "x" * 50,
            "ALLOWED_HOSTS": "example.com",
            "CACHE_DIR": str(custom_dir),
        },
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["CACHES"]["default"]["LOCATION"] == str(custom_dir)


def test_prod_cache_location_defaults_under_base_dir():
    """The other half of the same pin: with ``CACHE_DIR`` unset, ``LOCATION`` still falls back
    to a real, deployment-relative default (``BASE_DIR / "cache"``) rather than an empty or
    hardcoded-elsewhere path.

    ``isolate_dirs=False``: this test specifically wants the *real* default, so it deliberately
    accepts leaving a stray, empty ``cache/`` directory at the repo root as this one test's
    known side effect (10.3's carried-forward finding) rather than routing around it.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
        unset=["CACHE_DIR"],
        isolate_dirs=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["CACHES"]["default"]["LOCATION"] == str(BASE_DIR / "cache")


def test_prod_log_dir_follows_env_var(tmp_path):
    """10.15, the ``LOG_DIR`` equivalent of ``test_prod_cache_location_follows_cache_dir_env_var``
    above: setting ``LOG_DIR`` must change every rotating file handler's ``filename`` to exactly
    that directory, not merely to *some* path under it.
    """
    custom_dir = tmp_path / "custom-logs"
    result = _import_settings_module(
        "config.settings.prod",
        env={
            "SECRET_KEY": "x" * 50,
            "ALLOWED_HOSTS": "example.com",
            "LOG_DIR": str(custom_dir),
        },
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["LOG_DIR"] == str(custom_dir)
    handlers = data["LOGGING"]["handlers"]
    assert handlers["app_file"]["filename"] == str(custom_dir / "app.log")
    assert handlers["error_file"]["filename"] == str(custom_dir / "error.log")


def test_prod_log_dir_defaults_under_base_dir():
    """The other half of the same pin, and the same accepted trade-off as
    ``test_prod_cache_location_defaults_under_base_dir`` above: ``isolate_dirs=False`` so this
    test can see the real default (``BASE_DIR / "logs"``), accepting the stray directory (with
    two empty log files) as this one test's known side effect.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
        unset=["LOG_DIR"],
        isolate_dirs=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["LOG_DIR"] == str(BASE_DIR / "logs")


def test_prod_logging_has_rotating_app_and_error_files():
    """10.15, design.md "Logging and monitoring": rotating file handlers, and a *separate*
    ERROR-and-above log — not the same file re-used, and not a plain (non-rotating)
    ``FileHandler`` that would grow forever.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    handlers = json.loads(result.stdout)["LOGGING"]["handlers"]

    assert handlers["app_file"]["class"] == "logging.handlers.RotatingFileHandler"
    assert handlers["error_file"]["class"] == "logging.handlers.RotatingFileHandler"
    assert handlers["app_file"]["filename"] != handlers["error_file"]["filename"]
    assert handlers["error_file"]["level"] == "ERROR"
    # Bounded, not unbounded — an unrotated log file on a home server is exactly the kind of
    # slow disk-fill design.md's "Disk full -> SQLite corruption risk" edge case warns about.
    assert handlers["app_file"]["maxBytes"] > 0
    assert handlers["app_file"]["backupCount"] > 0
    assert handlers["error_file"]["maxBytes"] > 0
    assert handlers["error_file"]["backupCount"] > 0


def test_prod_logging_sentry_seam_is_off_by_default():
    """10.15: "off by default" must mean *nothing* Sentry-related runs when ``SENTRY_DSN`` is
    unset -- not merely that no events get sent. ``sentry_sdk`` is not a project dependency
    (see ``config/settings/prod.py``'s own comment), so this also proves importing
    ``config.settings.prod`` never requires it to be installed.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
        unset=["SENTRY_DSN"],
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["SENTRY_DSN"] == ""


def test_prod_logging_sentry_dsn_without_package_fails_loudly():
    """Setting ``SENTRY_DSN`` with ``sentry-sdk`` not installed must refuse to start, not
    silently run with no error reporting -- a misconfiguration that looks identical to "working,
    just quiet" is worse than one that fails at import time where an operator will see it.
    """
    result = _import_settings_module(
        "config.settings.prod",
        env={
            "SECRET_KEY": "x" * 50,
            "ALLOWED_HOSTS": "example.com",
            "SENTRY_DSN": "https://examplePublicKey@o0.ingest.sentry.io/0",
        },
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "SENTRY_DSN" in result.stderr


def test_prod_does_not_reenable_basic_authentication():
    """prod.py star-imports base, but must not override REST_FRAMEWORK to add Basic back."""
    result = _import_settings_module(
        "config.settings.prod",
        env={"SECRET_KEY": "x" * 50, "ALLOWED_HOSTS": "example.com"},
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    auth_classes = data["REST_FRAMEWORK"]["DEFAULT_AUTHENTICATION_CLASSES"]
    assert auth_classes == [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ]
    assert "rest_framework.authentication.BasicAuthentication" not in auth_classes
