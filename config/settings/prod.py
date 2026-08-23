"""Production settings — served behind Caddy via Docker Compose."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

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
