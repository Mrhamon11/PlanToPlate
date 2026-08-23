import string
from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import User
from accounts.services import (
    TEMP_PASSWORD_LIFETIME,
    complete_password_change,
    generate_temp_password,
    set_temp_password,
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


def test_complete_password_change_clears_flags(user_factory):
    user = user_factory()
    set_temp_password(user)

    complete_password_change(user, "BrandNewPassw0rd!")

    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.temp_password_expires_at is None
    assert user.check_password("BrandNewPassw0rd!") is True


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
