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

    On failure, the in-memory ``user`` is restored so a caller that catches the exception and
    later calls ``user.save()`` for an unrelated reason cannot commit a half-applied reset —
    ``must_change_password=True`` paired with a temp password the admin was never shown, which
    would lock the account with no way in. For an already-saved user this means the row's
    (rolled-back) database state, not literally "however the caller had it before this call" —
    a caller holding unrelated unsaved edits on the same instance (say an admin form's
    in-progress ``user.email`` change) loses them on this path too, since ``refresh_from_db()``
    cannot distinguish "changed by this function" from "changed by the caller". Mirrors
    ``complete_password_change``'s restoration below.
    """
    temp_password = generate_temp_password()
    had_pk = user.pk is not None
    previous_password = user.password
    previous_must_change_password = user.must_change_password
    previous_temp_password_expires_at = user.temp_password_expires_at
    user.set_password(temp_password)
    user.must_change_password = True
    user.temp_password_expires_at = timezone.now() + TEMP_PASSWORD_LIFETIME
    try:
        with transaction.atomic():
            if user.pk is None:
                user.save()
            else:
                user.save(
                    update_fields=[
                        "password",
                        "must_change_password",
                        "temp_password_expires_at",
                    ]
                )
            Token.objects.filter(user=user).delete()
    except Exception:
        if had_pk:
            try:
                # refresh_from_db() restores every concrete field from the (rolled-back) row
                # in one call, rather than hand-mirroring a field list that would silently go
                # stale the next time a field is added to this flow.
                user.refresh_from_db()
            except Exception:  # noqa: S110 — deliberately silent, see comment below
                # A concurrently deleted row would raise DoesNotExist here — swallowed rather
                # than left to replace the exception on the line below with an unrelated one.
                # Best-effort restore; the original failure is still what the caller sees.
                pass
        else:
            # There is no row to reload — the insert never committed, so pk is still None.
            # _state.adding is restored too, so the instance is exactly as it was handed in,
            # not merely "save() would still route to an INSERT" (which pk=None alone gives).
            user.password = previous_password
            user.must_change_password = previous_must_change_password
            user.temp_password_expires_at = previous_temp_password_expires_at
            user.pk = None
            user._state.adding = True
        # refresh_from_db() only reloads model fields — it does not know about `_password`,
        # AbstractBaseUser's own cache of the plaintext value passed to set_password(). Left
        # alone, a save() that fails before AbstractBaseUser.save() clears it would leave that
        # plaintext sitting on the in-memory instance even after the field restore above.
        user._password = None
        raise
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

    On failure, the in-memory ``user`` is restored to the (rolled-back) database's state — not
    literally "however the caller had it before this call": a caller holding unrelated unsaved
    edits on the same instance loses them here too, since ``refresh_from_db()`` cannot tell
    "changed by this function" apart from "changed by the caller". No caller today hits that
    case; see the same caveat on ``set_temp_password`` above.
    """
    validate_password(new_password, user=user)

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
        try:
            # refresh_from_db() restores every concrete field from the (rolled-back) row in
            # one call rather than hand-mirroring a field list that would silently go stale
            # the next time a field is added to this flow — the same treatment as
            # set_temp_password above.
            user.refresh_from_db()
        except Exception:  # noqa: S110 — deliberately silent, see comment below
            # A concurrently deleted row would raise DoesNotExist here — swallowed rather than
            # left to replace the exception on the line below with an unrelated one. Best-effort
            # restore; the original failure is still what the caller sees.
            pass
        # ...but it only reloads model fields, not `_password` (AbstractBaseUser's own cache
        # of the plaintext passed to set_password()) — cleared explicitly so a save() failing
        # before AbstractBaseUser.save() gets a chance to clear it doesn't leave that
        # plaintext sitting on the in-memory instance.
        user._password = None
        raise
