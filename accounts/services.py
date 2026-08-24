"""Business logic for the temp-password flow — see MILESTONES.md section 6 and
Plan/01-Users-And-Auth/design.md.

Views and the future ``bootstrap_admin`` management command call into this module rather than
touching ``User`` fields directly, so the "generate once, never store plaintext, revoke
atomically" rules live in exactly one place.
"""

import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import User

TEMP_PASSWORD_LIFETIME = timedelta(days=7)


def generate_temp_password() -> str:
    """A random, URL-safe password for one-time admin-issued credentials — never derived from
    the username or anything guessable.
    """
    return secrets.token_urlsafe(16)


def set_temp_password(user: User) -> str:
    """Issue a new temp password for ``user`` and return it in plaintext, exactly once.

    The caller (an admin view or the ``bootstrap_admin`` command) is responsible for
    displaying this return value — it is not persisted anywhere and cannot be retrieved again.

    Works whether ``user`` is already saved or still a bare, unsaved instance: ``save(
    update_fields=...)`` raises against a row with no primary key yet, so an unsaved user is
    saved in full instead. This lets ``bootstrap_admin`` (01.9) and the admin create-user flow
    (task 09) build a ``User(...)`` and call this directly, with no intermediate ``.save()``.

    Also revokes any existing DRF token for ``user`` — an admin re-issuing a temp password (a
    lost-credential recovery, say) must not leave the old credential's token still live.
    """
    temp_password = generate_temp_password()
    user.set_password(temp_password)
    user.must_change_password = True
    user.temp_password_expires_at = timezone.now() + TEMP_PASSWORD_LIFETIME
    with transaction.atomic():
        if user.pk is None:
            user.save()
        else:
            user.save(
                update_fields=["password", "must_change_password", "temp_password_expires_at"]
            )
        Token.objects.filter(user=user).delete()
    return temp_password


def temp_password_expired(user: User) -> bool:
    """Whether ``user``'s temp password has passed its deadline and login must be refused.

    ``temp_password_expires_at is None`` with ``must_change_password=True`` means "forced
    change, no deadline" (an admin ticked the flag by hand without setting an expiry) — not
    "expired". Only an explicit, past deadline counts, and only while a change is forced at all.
    """
    if not user.must_change_password or user.temp_password_expires_at is None:
        return False
    return timezone.now() > user.temp_password_expires_at


def complete_password_change(user: User, new_password: str) -> None:
    """Set ``new_password`` and clear the forced-change state as a single unit of work.

    Validated against ``AUTH_PASSWORD_VALIDATORS`` before anything is written. The password
    write, the flag-clearing write, and the token revocation happen inside one
    ``transaction.atomic()`` block, so there is no state where a changed password is paired
    with a stale "must change password" flag, a cleared flag is paired with the old password
    still active, or a surviving token outlives the reset that was meant to end it (design.md,
    "Security notes" — the same reasoning already applied to session cycling).

    On failure, the in-memory ``user`` is reset to its pre-call state so it does not disagree
    with the rolled-back database.
    """
    validate_password(new_password, user=user)

    previous_password = user.password
    previous_must_change_password = user.must_change_password
    previous_temp_password_expires_at = user.temp_password_expires_at
    try:
        with transaction.atomic():
            user.set_password(new_password)
            user.must_change_password = False
            user.temp_password_expires_at = None
            user.save(
                update_fields=["password", "must_change_password", "temp_password_expires_at"]
            )
            Token.objects.filter(user=user).delete()
    except Exception:
        user.password = previous_password
        user.must_change_password = previous_must_change_password
        user.temp_password_expires_at = previous_temp_password_expires_at
        raise
