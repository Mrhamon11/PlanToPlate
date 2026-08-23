"""Settings for the automated test suite — fast and hermetic."""

import os

# base.py reads SECRET_KEY at import time via ``env("SECRET_KEY")`` with no default, so it
# must already be set *before* the star-import below runs — otherwise this module's own
# import blows up on a machine with no .env (fresh clone, CI, the container), rather than the
# suite running hermetically as intended. setdefault() only sets it if nothing already has —
# so a SECRET_KEY already present in the process environment before pytest starts still wins.
# It does NOT defer to .env: django-environ's read_env() (inside the star-import below) does
# not overwrite a key that is already set in os.environ, so the dummy value set here wins over
# whatever .env contains.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-any-real-use")  # noqa: S105

from .base import *  # noqa: E402, F403

DEBUG = False

# Defined outright rather than patching base.DATABASES in place. Patching only NAME would
# leave ENGINE (and OPTIONS) inherited from whatever DATABASE_URL resolved to in base.py — if
# a developer points DATABASE_URL at a real Postgres server to check the portability promise
# (see MILESTONES.md) and then runs the suite, it must still run against in-memory SQLite,
# never against that server. Rebinding also avoids mutating config.settings.base's dict in
# place, which would leave it altered for anything importing it afterward. OPTIONS reuses
# base's SQLITE_OPTIONS (via the star-import) so the pragmas under test are the same object
# production configures, not a copy that can drift.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": dict(SQLITE_OPTIONS),  # noqa: F405
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
