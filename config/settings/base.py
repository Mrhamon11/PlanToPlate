"""Settings shared by every environment.

Nothing sensitive lives here. Every value that differs between a laptop and a server comes
from the environment via ``django-environ`` — see ``.env.example`` for the full list.
"""

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# django-environ reads a real .env file for local development. In prod the values come from
# the process environment directly (Docker Compose's env_file / environment keys), and reading
# a missing .env is a no-op rather than an error. DJANGO_ENV_FILE lets tests point at a
# different (or nonexistent) file to exercise the "no SECRET_KEY at all" path without a real
# .env on disk shadowing it.
_env_file = os.environ.get("DJANGO_ENV_FILE", str(BASE_DIR / ".env"))
environ.Env.read_env(_env_file)

# No default: a defaulted secret key means forgeable sessions. Missing it must fail loudly.
SECRET_KEY = env("SECRET_KEY")

DEBUG = env.bool("DEBUG")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "core",
    "accounts",
    "catalog",
    "recipes",
    "meals",
    "lists",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

# Every environment sets these connection options for SQLite. Missing them is how you get
# "database is locked" under two concurrent writers. Named so config.settings.test can reuse
# the identical block instead of keeping a copy that can drift out of step.
SQLITE_OPTIONS = {
    "init_command": (
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; "
        "PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;"
    ),
    "transaction_mode": "IMMEDIATE",
}

# Conditional on the engine so pointing DATABASE_URL at Postgres does not explode — this is
# the portability promise made real.
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"]["OPTIONS"] = dict(SQLITE_OPTIONS)


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Authentication
# Session cookies, not JWT — see MILESTONES.md for the rationale. SESSION_SAVE_EVERY_REQUEST
# plus a one-year age satisfies "stay logged in until logout."
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"


# Django REST Framework
# Default-deny is deliberate: an endpoint that forgets its permission class should fail
# closed, not open.
REST_FRAMEWORK = {
    # Explicit on purpose: DRF's built-in default is [SessionAuthentication,
    # BasicAuthentication], which would silently accept Authorization: Basic on every
    # endpoint with no throttle guarding it. MILESTONES.md lists only sessions and (later)
    # TokenAuthentication. TokenAuthentication is appended in task 01 — its migration needs
    # an FK to AUTH_USER_MODEL, which does not exist until the custom User model lands.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PlanToPlate API",
    "DESCRIPTION": "Recipes, meal planning, and shopping lists.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # drf-spectacular serves the schema and Swagger UI to AllowAny by default, which would
    # override the default-deny above and publish the full API shape anonymously. There is no
    # anonymous access anywhere in this app (MILESTONES.md section 4).
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}
