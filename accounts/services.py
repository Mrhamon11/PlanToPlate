"""Business logic for the temp-password flow — see MILESTONES.md section 6 and
Plan/01-Users-And-Auth/design.md.

Views and the future ``bootstrap_admin`` management command call into this module rather than
touching ``User`` fields directly, so the "generate once, never store plaintext, clear
atomically" rules live in exactly one place.
"""

import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from accounts.models import User

TEMP_PASSWORD_LIFETIME = timedelta(days=7)


def generate_temp_password() -> str:
    """Return a random, URL-safe password suitable for one-time admin-issued credentials.

    Never derived from the username or anything guessable. ``token_urlsafe(16)`` yields
    roughly 22 characters from a 128-bit random value — comfortably past the project's
    10-character minimum with room to spare.
    """
    return secrets.token_urlsafe(16)


def set_temp_password(user: User) -> str:
    """Issue a new temp password for ``user`` and return it in plaintext, exactly once.

    The caller (an admin view or the ``bootstrap_admin`` command) is responsible for
    displaying this return value to the admin — it is not persisted anywhere, and there is no
    way to retrieve it again after this call returns.

    Works whether ``user`` is already saved or still a bare, unsaved instance: an unsaved user
    (``user.pk is None``) is saved in full rather than via ``update_fields``, since Django's
    ``save(update_fields=...)`` unconditionally issues an ``UPDATE`` and raises
    ``ValueError: Cannot force an update in save() with no primary key`` against a row that
    does not exist yet. This lets ``bootstrap_admin`` (01.9) and the admin create-user flow
    (task 09) build a ``User(...)`` and call this directly instead of having to remember an
    intermediate ``.save()`` first.
    """
    temp_password = generate_temp_password()
    user.set_password(temp_password)
    user.must_change_password = True
    user.temp_password_expires_at = timezone.now() + TEMP_PASSWORD_LIFETIME
    if user.pk is None:
        user.save()
    else:
        user.save(update_fields=["password", "must_change_password", "temp_password_expires_at"])
    return temp_password


def complete_password_change(user: User, new_password: str) -> None:
    """Set ``new_password`` and clear the forced-change state as a single unit of work.

    Validated against ``AUTH_PASSWORD_VALIDATORS`` before anything is written. The password
    write and the flag-clearing write happen in one ``save(update_fields=...)`` call — a
    single statement is atomic by construction, so there is no mid-way state where a changed
    password could be paired with a stale "must change password" flag (relocking the user out
    of their own new credentials), or a cleared flag could be paired with the old password
    still active (silently dropping the forced reset).
    """
    validate_password(new_password, user=user)

    user.set_password(new_password)
    user.must_change_password = False
    user.temp_password_expires_at = None
    user.save(update_fields=["password", "must_change_password", "temp_password_expires_at"])
