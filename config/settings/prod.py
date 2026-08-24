"""Production settings — served behind Caddy via Docker Compose."""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, env

DEBUG = False

# DRF's ScopedRateThrottle keys its cache entry on request.META["REMOTE_ADDR"] unless a
# X-Forwarded-For header is present, in which case NUM_PROXIES=None (DRF's default, left
# in place in base.py) trusts the *entire* client-supplied header as the ident. Caddy's
# reverse_proxy appends the real peer address to whatever X-Forwarded-For the client sent
# rather than replacing it, so with NUM_PROXIES unset an attacker who rotates that header on
# every request gets a fresh throttle bucket each time — reproduced live during review: 20
# wrong-password POSTs with a rotating header, zero 429s. NUM_PROXIES=1 makes DRF take the
# single trusted hop Caddy appended (the last comma-separated entry) instead of the whole
# header. Set here, not in base.py: under `runserver` with no proxy in front, NUM_PROXIES=1
# would instead trust the *last* entry of a still fully attacker-controlled header, which is
# no better than the status quo — dev and test must keep DRF's REMOTE_ADDR-only default.
# Belt and braces with the Caddyfile's `header_up X-Forwarded-For {remote_host}`, which
# overwrites rather than appends, making the ident correct even if this setting were ever
# lost.
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

# Django's DEFAULT_LOGGING gates its console handler on require_debug_true and routes errors
# to mail_admins otherwise — with DEBUG=False and no ADMINS/email configured here, unhandled
# 500s are silently discarded. This is the only telemetry a self-hosted single-box deployment
# has: send django and django.request to stderr, which `docker compose logs` already captures.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
