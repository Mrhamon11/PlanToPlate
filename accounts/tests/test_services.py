import string
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import User
from accounts.services import (
    TEMP_PASSWORD_LIFETIME,
    complete_password_change,
    generate_temp_password,
    set_temp_password,
    temp_password_expired,
)

pytestmark = pytest.mark.django_db


def test_generate_temp_password_length_and_charset():
    password = generate_temp_password()

    assert len(password) >= 12
    allowed_chars = set(string.ascii_letters + string.digits + "-_")
    assert set(password) <= allowed_chars


def test_generate_temp_password_is_unique():
    passwords = {generate_temp_password() for _ in range(100)}

    assert len(passwords) == 100


def test_set_temp_password_sets_flags(user_factory):
    user = user_factory()
    before = timezone.now()

    set_temp_password(user)

    after = timezone.now()
    user.refresh_from_db()
    assert user.must_change_password is True
    assert before + TEMP_PASSWORD_LIFETIME <= user.temp_password_expires_at
    assert user.temp_password_expires_at <= after + TEMP_PASSWORD_LIFETIME


def test_temp_password_not_stored_plaintext(user_factory):
    user = user_factory()

    temp_password = set_temp_password(user)

    user.refresh_from_db()
    for field in user._meta.concrete_fields:
        value = getattr(user, field.attname)
        assert temp_password not in str(value)


def test_set_temp_password_on_unsaved_user_persists():
    """``set_temp_password`` must also work against a bare, unsaved instance.

    ``bootstrap_admin`` (01.9) and the admin create-user flow (task 09) build a ``User(...)``
    and call this directly, before any ``.save()`` of their own. ``save(update_fields=...)``
    raises ``ValueError`` against a row with no primary key, so the ``user.pk is None`` branch
    must fall back to a full ``save()`` instead — this proves that branch actually persists the
    row, rather than merely not crashing.
    """
    user = User(username="freshadmin")
    assert user.pk is None

    temp_password = set_temp_password(user)

    assert user.pk is not None
    saved = User.objects.get(username="freshadmin")
    assert saved.check_password(temp_password) is True
    assert saved.must_change_password is True
    assert saved.temp_password_expires_at is not None


def test_set_temp_password_revokes_existing_tokens(user_factory):
    """An admin re-issuing a temp password must not leave the old credential's token live.

    The only thing that would otherwise still block that token is
    ForcePasswordChangeAPIPermission, sitting in DEFAULT_PERMISSION_CLASSES — and
    LogoutAPIView already demonstrates how easily a view opts out of that list.
    """
    user = user_factory()
    token = Token.objects.create(user=user)

    set_temp_password(user)

    assert not Token.objects.filter(pk=token.pk).exists()


def test_set_temp_password_rolls_back_on_token_delete_failure(user_factory):
    """``transaction.atomic()`` around ``set_temp_password``'s save-then-revoke must cover the
    token delete too, mirroring
    ``test_complete_password_change_rolls_back_on_token_delete_failure``.

    Without ``atomic()``, a delete failure here would leave the user's password already
    overwritten with the new temp password (and ``must_change_password``/expiry already set)
    while the old token stays live — a half-applied credential reset with no way back for the
    admin who thinks they just issued a fresh temp password.
    """
    user = user_factory()
    original_password_hash = user.password
    Token.objects.create(user=user)

    with (
        patch(
            "accounts.services.Token.objects.filter",
            side_effect=RuntimeError("simulated delete failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        set_temp_password(user)

    user.refresh_from_db()
    assert user.password == original_password_hash
    assert user.must_change_password is False
    assert user.temp_password_expires_at is None
    assert Token.objects.filter(user=user).exists()


def test_complete_password_change_clears_flags(user_factory):
    user = user_factory()
    set_temp_password(user)

    complete_password_change(user, "BrandNewPassw0rd!")

    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.temp_password_expires_at is None
    assert user.check_password("BrandNewPassw0rd!") is True


@pytest.mark.parametrize(
    ("must_change_password", "expires_at_offset", "expected"),
    [
        # Forced change, no deadline set (an admin ticking must_change_password by hand in
        # Django Admin without also setting an expiry) — "forced change, no deadline", not
        # "expired". Pinned explicitly, per design.md: a future refactor that dropped the
        # must_change_password check would flip this to True and permanently lock out anyone
        # in this state, since user_can_authenticate gates both authenticate() and get_user().
        (True, None, False),
        (True, timedelta(days=-1), True),
        (True, timedelta(days=1), False),
        # must_change_password already False must never read as "expired", regardless of what
        # is left in temp_password_expires_at (e.g. a stale past value the flag-clear did not
        # happen to null out through some other code path).
        (False, timedelta(days=-1), False),
    ],
)
def test_temp_password_expired_pinned_semantics(
    user_factory, must_change_password, expires_at_offset, expected
):
    user = user_factory()
    user.must_change_password = must_change_password
    user.temp_password_expires_at = (
        None if expires_at_offset is None else timezone.now() + expires_at_offset
    )
    user.save(update_fields=["must_change_password", "temp_password_expires_at"])

    assert temp_password_expired(user) is expected


def test_complete_password_change_revokes_existing_tokens(user_factory):
    """A leaked token must not survive the password change meant to end it.

    complete_password_change is the shared choke point for both the HTML and API change paths
    (CLAUDE.md §6) — session cycling on password change was already mandatory (design.md,
    "Security notes"); a DRF token has no relationship to the password hash at all, so without
    an explicit revocation here it would keep working indefinitely after a "successful" reset.
    """
    user = user_factory()
    token = Token.objects.create(user=user)

    complete_password_change(user, "BrandNewPassw0rd!")

    assert not Token.objects.filter(pk=token.pk).exists()


def test_complete_password_change_rolls_back_on_token_delete_failure(user_factory):
    """``transaction.atomic()`` must cover the token delete too, not just the ``save()``.

    The only prior coverage of atomicity here (below) fails ``save()``, so the token delete is
    never reached — that test would pass identically with no ``atomic()`` at all. This exercises
    the direction that actually needs it: if the delete fails after the save already ran inside
    the same transaction, the save must roll back too, or a "successful" password change leaves
    a leaked token alive with the old password still valid.
    """
    user = user_factory()
    temp_password = set_temp_password(user)
    Token.objects.create(user=user)

    with (
        patch(
            "accounts.services.Token.objects.filter",
            side_effect=RuntimeError("simulated delete failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        complete_password_change(user, "BrandNewPassw0rd!")

    user.refresh_from_db()
    assert user.check_password(temp_password) is True
    assert user.must_change_password is True
    assert user.temp_password_expires_at is not None
    assert Token.objects.filter(user=user).exists()
    # The in-memory instance must not disagree with the rolled-back database either.
    assert user.check_password("BrandNewPassw0rd!") is False
    assert user.must_change_password is True


def test_complete_password_change_restores_in_memory_state_on_failure(user_factory):
    """The ``except`` block's manual field restoration is exercised directly, before any
    ``refresh_from_db()`` call masks it.

    ``test_complete_password_change_rolls_back_on_token_delete_failure`` (above) only asserts
    against a *freshly reloaded* instance, which trivially matches the database regardless of
    whether ``complete_password_change`` restores its caller's in-memory ``user`` object — that
    test would pass identically if the ``except`` block that resets ``user.password`` /
    ``user.must_change_password`` / ``user.temp_password_expires_at`` were deleted entirely.
    This checks the same instance the caller is left holding, immediately after the exception,
    with no reload in between.
    """
    user = user_factory()
    temp_password = set_temp_password(user)
    Token.objects.create(user=user)
    previous_password_hash = user.password
    previous_expires_at = user.temp_password_expires_at

    with (
        patch(
            "accounts.services.Token.objects.filter",
            side_effect=RuntimeError("simulated delete failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        complete_password_change(user, "BrandNewPassw0rd!")

    assert user.password == previous_password_hash
    assert user.must_change_password is True
    assert user.temp_password_expires_at == previous_expires_at
    assert user.check_password(temp_password) is True
    assert user.check_password("BrandNewPassw0rd!") is False


def test_complete_password_change_is_a_single_write(user_factory):
    """The password write and the flag-clearing write are one ``save()`` call, not two.

    Collapsed into a single ``save(update_fields=[...])`` call rather than split across
    separate saves — this proves the collapse actually happened and covers every field the
    change touches. It does not simulate or prove recovery from a partial multi-write failure;
    once there is only one ``save()`` call, there is no mid-way state left to recover from, and
    manufacturing one here would reintroduce the split-write anti-pattern this design removes.
    The incidental fact that the patched ``save`` raises before writing anything is just how a
    single mocked call is observed here, not a claim about atomicity across multiple writes.
    """
    user = user_factory()
    temp_password = set_temp_password(user)

    save_calls: list[list[str] | None] = []

    def failing_save(self, *args, **kwargs):
        save_calls.append(kwargs.get("update_fields"))
        raise RuntimeError("simulated write failure")

    with patch.object(type(user), "save", failing_save), pytest.raises(RuntimeError):
        complete_password_change(user, "BrandNewPassw0rd!")

    assert len(save_calls) == 1
    assert set(save_calls[0]) == {"password", "must_change_password", "temp_password_expires_at"}

    user.refresh_from_db()
    assert user.check_password(temp_password) is True
    assert user.must_change_password is True
    assert user.temp_password_expires_at is not None
