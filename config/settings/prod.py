"""Production settings — served behind Caddy via Docker Compose."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import BASE_DIR, REST_FRAMEWORK, env

DEBUG = False

# DRF's ScopedRateThrottle keys its cache entry on request.META["REMOTE_ADDR"] only when
# NUM_PROXIES is 0; left at DRF's own default (None), get_ident() instead trusts the *entire*
# client-supplied X-Forwarded-For header verbatim whenever one is present — with an attacker
# rotating that header on every request getting a fresh throttle bucket each time, reproduced
# live during review as a complete login-throttle bypass (20 wrong-password POSTs with a
# rotating header, zero 429s).
#
# Corrected 10.8 (was previously wrong here): Caddy's reverse_proxy does not append to a
# client-supplied X-Forwarded-For the way this comment used to claim — it REPLACES it by
# default, whenever `trusted_proxies` is unset (verified at runtime against the pinned
# caddy:2.10.2-alpine image; see the Caddyfile's own header_up line and comment, which
# document the same fact and are currently redundant with Caddy's built-in default). In this
# deployment's actual topology the header reaching Django therefore always already contains
# exactly one value: the real peer.
#
# NUM_PROXIES=1 is still set explicitly rather than left at None, as genuine belt-and-braces:
# it makes DRF take the single rightmost comma-separated entry rather than trusting whatever
# arrives verbatim, which stays correct if the Caddyfile's header_up line is ever removed, if
# `trusted_proxies` is ever configured (switching Caddy to *append* onto a now-trusted chain
# instead of replacing outright), or if some other reverse proxy is ever substituted for
# Caddy — none of which should silently reopen the header-rotation bypass this setting closes.
# Set here, not in base.py: under `runserver` with no proxy in front, NUM_PROXIES=1 would
# instead trust the *last* entry of a still fully attacker-controlled header, which is no
# better than the status quo — dev and test must keep DRF's REMOTE_ADDR-only default.
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": 1}

# Nothing in base.py declares CACHES, so Django's default LocMemCache applies everywhere —
# fine for dev (`runserver` is one process) and for the test suite (one process, and
# conftest.py's autouse _clear_cache fixture resets it between tests), but wrong here:
# docker-entrypoint.sh starts gunicorn with --workers 2, and LocMemCache is per-process, so
# the login throttle (01.8) would actually enforce 10/min across the two workers' independent
# counters, not the 5/min design.md specifies, and any counter resets on a worker recycle.
# FileBasedCache is shared across processes (it stores each entry as a file) with no new
# dependency and no database table to create — Redis/memcached would be overkill at this
# scale, and DatabaseCache needs `createcachetable`, a data-mutating command outside what this
# task is authorised to run. CACHE_DIR mirrors DATABASE_URL's pattern (D16): the
# container-specific default lives in compose.yaml, not baked in here, so this still works
# unchanged for a bare `uv run` against config.settings.prod outside Docker.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": env("CACHE_DIR", default=str(BASE_DIR / "cache")),  # noqa: F405
    }
}

# 127.0.0.1 is appended for the Compose healthcheck probe, which hits the container
# directly and cannot use the public hostname. The app port is not published; only
# Caddy can reach it.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS") + ["127.0.0.1"]

# Django's own Host-header validation is the only thing standing between a cache-poisoning /
# password-reset-link-forging request and this app once DEBUG=False turns off the "invalid
# HTTP_HOST header" debug page -- a wildcard here does not fail any of Django's own system
# checks (security.W020 only fires on an *empty* ALLOWED_HOSTS), so it is worth refusing
# outright rather than trusting an operator's .env never contains it (10.3, design.md
# "genuinely restrictive").
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must not contain '*' in production -- it defeats Django's Host-header "
        "validation entirely. List the real hostname(s) this deployment answers to instead."
    )

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Caddy terminates TLS and forwards over plain HTTP; this header is how Django learns the
# original request was HTTPS so SECURE_SSL_REDIRECT and secure cookies behave correctly.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = True
# Dev runs over plain HTTP, so this stays out of base.py — a Secure cookie there would never
# come back from the browser and would silently break local login.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# The container healthcheck reaches gunicorn directly, without Caddy's X-Forwarded-Proto,
# so an unexempted /healthz/ would answer 301 and never touch the database — reporting
# "healthy" from a container whose database is actually down.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]

SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True

# Django's own default already matches this ("same-origin" since Django 3.1) — set explicitly
# per design.md's security-headers block so it is asserted rather than merely inherited, and so
# a future Django release changing its default cannot silently change this deployment's
# behaviour.
SECURE_REFERRER_POLICY = "same-origin"

# Also already Django's own default ("DENY" since Django 3.0) — same reasoning as
# SECURE_REFERRER_POLICY above: pinned explicitly rather than relied upon implicitly. Combined
# with CSP's own `frame-ancestors 'none'` (10.4) for browsers that only honour one or the other.
X_FRAME_OPTIONS = "DENY"

# Empty by default: this deployment is single-origin (Caddy fronts one host per design.md's
# topology), and Django only needs an entry here when a POST's Origin header would otherwise
# fail to match request.get_host() -- a second valid hostname for the same app (a public domain
# alongside a Tailscale name), or a reverse proxy that rewrites Host. Left unset, nothing here
# breaks; an operator serving the same app under more than one hostname sets this to the full
# origin(s), e.g. "https://plantoplate.example.com".
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Django's DEFAULT_LOGGING gates its console handler on require_debug_true and routes errors
# to mail_admins otherwise — with DEBUG=False and no ADMINS/email configured here, unhandled
# 500s would otherwise be silently discarded (D21). `docker compose logs` still captures the
# console handler below, but a self-hosted box also needs on-disk history that survives a
# container restart (the log volume, not the writable layer) and rotates instead of growing
# forever — 10.15, design.md "Logging and monitoring".
#
# CACHE_DIR (above) sets the precedent this follows: an env-overridable directory, defaulted
# under BASE_DIR so a bare `uv run` against config.settings.prod outside Docker still works,
# with the container-specific default supplied by compose.prod.yaml instead of baked in here.
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))  # noqa: F405


def _logging_config(log_dir: Path) -> dict:
    """Builds the ``LOGGING`` dict for a given directory.

    Extracted into a function — rather than inlined directly into the module-level ``LOGGING``
    assignment below — so a test can build the exact same handler configuration against a
    scratch directory and read the files it actually writes
    (``core/tests/test_ops.py::test_logging_excludes_passwords``), instead of only reasoning
    about what reaches a handler indirectly through ``caplog``.

    Two rotating file handlers, not one: ``app.log`` carries everything at ``INFO`` and above
    (the day-to-day request/response trail), and ``error.log`` carries only ``ERROR`` and above
    — a separate file per design.md, so an operator chasing down a production incident does not
    have to grep a week of routine traffic to find the handful of lines that actually matter.
    Both are capped at 10 MB x 5 backups (50 MB) each, the same retention shape already chosen
    for the container's own json-file log driver (10.7, ``compose.prod.yaml``).

    Never logs a credential itself — nothing in this project's own code logs a password,
    session key, or raw request body on an auth endpoint (grepped during 10.15; the temp-
    password flow's one intentional exception, printing a freshly bootstrapped admin's password
    to stdout once, is `bootstrap_admin`'s own documented behaviour — D27 — not something this
    LOGGING config touches). Django's own request-logging path never includes local variable
    values in a plain (non-HTML) traceback, so a stray unhandled exception during a login POST
    cannot smuggle the submitted password into ``error.log`` either.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{asctime} {levelname} {name} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_dir / "app.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "formatter": "verbose",
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_dir / "error.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "level": "ERROR",
                "formatter": "verbose",
            },
        },
        "loggers": {
            "django": {
                "handlers": ["console", "app_file", "error_file"],
                "level": "INFO",
            },
            "django.request": {
                "handlers": ["console", "app_file", "error_file"],
                "level": "ERROR",
                "propagate": False,
            },
        },
    }


LOGGING = _logging_config(LOG_DIR)

# Optional Sentry seam (10.15, design.md: "off by default, DSN from env — a home server with no
# error reporting is fine, but the seam should exist"). `sentry-sdk` is deliberately NOT added
# to the `prod` dependency group: CLAUDE.md requires permission to add a dependency, and every
# deployment of this app to date runs with SENTRY_DSN unset, so there is nothing to gain from
# carrying an always-installed package nobody has asked to use yet. Left unset, this block is a
# complete no-op — importing sentry_sdk is skipped entirely, not merely uninitialized. An
# operator who wants Sentry adds the dependency themselves (`uv add --group prod sentry-sdk`)
# and sets SENTRY_DSN; a DSN with no package installed fails loudly at startup rather than
# silently shipping no error reports, so the misconfiguration is never mistaken for "it's just
# not sending anything yet".
SENTRY_DSN = env("SENTRY_DSN", default="")  # noqa: S105 - an env var name, not a secret
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
    except ImportError as exc:
        raise ImproperlyConfigured(
            "SENTRY_DSN is set but sentry-sdk is not installed. Add it with "
            "`uv add --group prod sentry-sdk`, or unset SENTRY_DSN to run without error "
            "reporting."
        ) from exc

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Never send request bodies/user PII to a third party by default — matches this file's
        # own LOGGING policy of never letting a credential leave the box.
        send_default_pii=False,
    )
