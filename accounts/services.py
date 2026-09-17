"""Business logic for the temp-password flow and admin account administration — see
MILESTONES.md section 6 and Plan/01-Users-And-Auth/design.md / Plan/09-Admin-Control-Center/
design.md ("User management").

Views, the ``bootstrap_admin`` management command, and the admin's custom create-user /
reset-password / entitlement / delete flows call into this module rather than touching
``User`` fields directly, so the "generate once, never store plaintext, revoke atomically"
rules — and the last-admin guard — live in exactly one place.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import QuerySet
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


# --- Admin account administration (task 09.5–09.8) ------------------------------------------


class LastAdminError(Exception):
    """The requested change would remove admin access from the only account that has it —
    refused, because a self-hosted app has no recovery path once every admin is locked out
    (design.md, "Entitle as admin" / "Edge cases").
    """


def active_admins() -> QuerySet[User]:
    """Every account that can currently reach the admin: ``is_staff`` and ``is_active``.

    ``PlanToPlateAdminSite.has_permission`` also excludes an account mid-forced-password-change,
    but that state is transient (it clears the moment they set a real password) — a temporary
    block is not the same as having lost admin access, so the last-admin guard does not count
    it against them.
    """
    return User.objects.filter(is_staff=True, is_active=True)


def is_last_admin(user: User) -> bool:
    """Whether ``user`` is the only active admin — so demoting or deleting them locks everyone
    out.
    """
    if not (user.is_staff and user.is_active):
        return False
    return not active_admins().exclude(pk=user.pk).exists()


def invalidate_sessions(user: User) -> int:
    """Delete every server-side session belonging to ``user``.

    Resetting a possibly-compromised password is pointless if the attacker's existing session
    survives (design.md, "Reset password"). ``set_temp_password``'s hash cycle already fails
    the session-auth-hash check on the next request; this removes the rows outright so nothing
    lingers. DB session backend only (``SESSION_ENGINE``); returns the count removed.
    """
    from django.contrib.sessions.models import Session

    target = str(user.pk)
    keys = [
        session.session_key
        for session in Session.objects.iterator()
        if session.get_decoded().get("_auth_user_id") == target
    ]
    if not keys:
        return 0
    Session.objects.filter(pk__in=keys).delete()
    return len(keys)


def create_user(
    *,
    actor: User,
    username: str,
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    is_staff: bool = False,
) -> tuple[User, str]:
    """Provision a new account with a one-time temp password (design.md, "Create user").

    Returns ``(user, temp_password)``. The caller must show the password exactly once and
    never persist it — ``set_temp_password`` already stores only its hash, forces a change,
    and sets the 7-day expiry. Emits the audit records for the temp password and, if the new
    account is staff, the entitlement grant.

    The account write and its audit records share one transaction: a failed ``LogEntry``
    insert rolls the new account back rather than leaving an issued-but-unrecorded password.
    """
    from core.services import audit

    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_staff=is_staff,
    )
    with transaction.atomic():
        temp_password = set_temp_password(user)
        audit.record_temp_password_issued(actor=actor, target=user, context="user created")
        if is_staff:
            audit.record_entitlement_change(actor=actor, target=user, granted=True)
    return user, temp_password


def reset_password(*, actor: User, user: User) -> str:
    """Issue ``user`` a fresh temp password, force a change, reset the expiry, and kill every
    session they hold (design.md, "Reset password"). Returns the new temp password to show
    once. Emits the temp-password audit record.

    The password write, the session kill, and the audit record share one transaction — a
    failed ``LogEntry`` insert must not leave a reset password with no trail.
    """
    from core.services import audit

    with transaction.atomic():
        temp_password = set_temp_password(user)
        invalidate_sessions(user)
        audit.record_temp_password_issued(actor=actor, target=user, context="admin reset")
    return temp_password


def set_entitlement(*, actor: User, user: User, is_staff: bool) -> bool:
    """Grant or revoke ``user``'s admin entitlement (``is_staff``).

    Refuses to demote the last active admin (``LastAdminError``). A no-op change writes
    nothing and emits no audit record. Returns ``True`` if a change was applied.
    """
    from core.services import audit

    if user.is_staff == is_staff:
        return False
    if not is_staff and is_last_admin(user):
        raise LastAdminError(
            f"{user.username} is the only active admin — grant another account admin access "
            "before removing this one's."
        )
    user.is_staff = is_staff
    user.save(update_fields=["is_staff"])
    audit.record_entitlement_change(actor=actor, target=user, granted=is_staff)
    return True


def delete_user(*, actor: User, user: User) -> None:
    """Delete ``user`` and everything ``OwnedModel.owner`` CASCADEs from them.

    Refuses to delete the last active admin (``LastAdminError``). Runs two pre-passes before
    ``user.delete()``, all in the same transaction as the delete itself:

    1. **D53 PROTECT-clearing** (``meals.services.dishes`` /
       ``recipes.services.components``): ``DishComponent.recipe`` and
       ``RecipeComponent.ingredient``/``sub_recipe`` are ``on_delete=PROTECT``, deliberately —
       so an ordinary single-recipe/ingredient delete cannot be pulled out from under a
       dependent. Left alone that also blocks *this* whole-account delete, on both the
       everyday case (the user's own recipe is in their own dish) and the sharing case (a
       bystander's dish/recipe uses something this user shared) — Django's collector has no
       notion of "already scheduled for deletion in this same call". Self-owned blockers are
       deleted outright; cross-owner ones are neutralized (``SET_NULL`` + graceful
       degradation), never silently refused.
    2. **D41 tombstoning** (``lists.signals``): a two-FK generated ``ListItem`` on a
       *bystander's* shopping list is stamped with fallback text so it is not caught in the
       cascade's crossfire (``ARCHITECTURE.md`` D41; ``design.md``, "Delete user").

    The audit ``LogEntry`` for the deletion itself is written by the admin layer (Django's
    ``ModelAdmin.log_deletion``), consistent with every other admin delete.
    """
    from lists.signals import tombstone_items_for_owner_deletion
    from meals.services.dishes import (
        neutralize_protect_blockers_for_owner_deletion as neutralize_dish_components,
    )
    from recipes.services.components import (
        neutralize_protect_blockers_for_owner_deletion as neutralize_recipe_components,
    )

    if is_last_admin(user):
        raise LastAdminError(
            f"{user.username} is the only active admin — deleting this account locks everyone "
            "out, with no recovery path."
        )
    with transaction.atomic():
        neutralize_dish_components(user)
        neutralize_recipe_components(user)
        tombstone_items_for_owner_deletion(user)
        user.delete()
