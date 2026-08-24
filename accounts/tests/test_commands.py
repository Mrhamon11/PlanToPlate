"""Tests for ``manage.py bootstrap_admin`` (subtask 01.9)."""

import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

pytestmark = pytest.mark.django_db


def test_bootstrap_admin_creates_superuser():
    stdout = io.StringIO()

    call_command("bootstrap_admin", stdout=stdout)

    user_model = get_user_model()
    user = user_model.objects.get(username="admin")
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.must_change_password is True
    assert user.temp_password_expires_at is not None

    output = stdout.getvalue()
    assert "Temporary password" in output

    # The password printed must be the one that was actually set — not just a message that
    # claims one was created.
    printed_line = next(
        line for line in output.splitlines() if line.startswith("Temporary password")
    )
    printed_password = printed_line.split(": ", 1)[1]
    assert user.check_password(printed_password) is True


def test_bootstrap_admin_idempotent(user_factory):
    user_factory(username="existing-admin", is_staff=True, is_superuser=True)
    stdout = io.StringIO()

    call_command("bootstrap_admin", stdout=stdout)

    user_model = get_user_model()
    assert user_model.objects.filter(is_superuser=True).count() == 1
    assert not user_model.objects.filter(username="admin").exists()
    assert "already exists" in stdout.getvalue()


def test_bootstrap_admin_reports_username_clash(user_factory):
    """A non-admin user already holding the requested username is a real, if unlikely,
    misconfiguration — the command must fail loudly with a clear message rather than let an
    ``IntegrityError`` surface as an unhandled traceback.
    """
    user_factory(username="admin", is_staff=False, is_superuser=False)

    with pytest.raises(CommandError, match="already taken by a non-admin account"):
        call_command("bootstrap_admin", stdout=io.StringIO())


def test_bootstrap_admin_rejects_empty_username():
    """An empty ``--username`` used to succeed silently and create a superuser no login form
    could ever reach (``AuthenticationForm``'s username field is required) — with both this
    command's own idempotence and the entrypoint's on-disk marker then blocking any retry,
    permanently. Must fail loudly instead, before creating anything.
    """
    with pytest.raises(CommandError, match="Invalid --username"):
        call_command("bootstrap_admin", "--username", "", stdout=io.StringIO())

    assert not get_user_model().objects.filter(is_superuser=True).exists()


def test_bootstrap_admin_rejects_invalid_username_characters():
    """A username failing ``UnicodeUsernameValidator`` used to persist verbatim — the account
    would exist but Django Admin refuses to save it without renaming first. Must fail loudly
    instead, before creating anything.
    """
    with pytest.raises(CommandError, match="Invalid --username"):
        call_command("bootstrap_admin", "--username", "bad name!", stdout=io.StringIO())

    assert not get_user_model().objects.filter(is_superuser=True).exists()


def test_bootstrap_admin_ignores_inactive_superuser_under_another_name(user_factory):
    """A superuser that was deactivated by mistake must not permanently block re-bootstrapping
    — otherwise a deployment with its only admin account disabled has no way back in at all,
    since neither a manual rerun nor a container restart (the entrypoint's own marker) would
    ever retry a command that believes an admin already exists.

    This is the case where the requested username is still free; the far more likely one — the
    deactivated admin *is* ``admin`` — is the next test down.
    """
    user_factory(username="disabled-admin", is_staff=True, is_superuser=True, is_active=False)
    stdout = io.StringIO()

    call_command("bootstrap_admin", stdout=stdout)

    user_model = get_user_model()
    created = user_model.objects.get(username="admin")
    assert created.is_superuser is True
    assert created.is_active is True
    assert "Created admin user" in stdout.getvalue()


def test_bootstrap_admin_refuses_deactivated_admin_at_the_same_username(user_factory):
    """The realistic shape of the deactivated-admin scenario, since the command creates its
    superuser at the default username in the first place: the deactivated admin *is* ``admin``.

    Skipping the idempotence check then walks straight into the unique constraint. The
    resulting error must name the case that actually occurred — reporting it as "taken by a
    non-admin account" sent the operator off to create a second superuser under another name
    rather than recovering the one they have.
    """
    user_factory(username="admin", is_staff=True, is_superuser=True, is_active=False)

    with pytest.raises(CommandError, match="already taken by a deactivated admin account"):
        call_command("bootstrap_admin", stdout=io.StringIO())

    user_model = get_user_model()
    assert user_model.objects.count() == 1
    assert user_model.objects.get(username="admin").is_active is False


def test_bootstrap_admin_force_reactivates_the_admin_it_refused(user_factory):
    """``--force`` is the recovery the refusal above points at: it must actually work, and on
    the account that already exists rather than beside it.
    """
    disabled = user_factory(username="admin", is_staff=True, is_superuser=True, is_active=False)
    stdout = io.StringIO()

    call_command("bootstrap_admin", "--force", stdout=stdout)

    user_model = get_user_model()
    assert user_model.objects.count() == 1
    disabled.refresh_from_db()
    assert disabled.is_active is True
    assert disabled.is_staff is True
    assert disabled.is_superuser is True
    assert disabled.must_change_password is True
    assert disabled.temp_password_expires_at is not None

    output = stdout.getvalue()
    assert "Reset admin user" in output
    printed_line = next(
        line for line in output.splitlines() if line.startswith("Temporary password")
    )
    assert disabled.check_password(printed_line.split(": ", 1)[1]) is True


def test_bootstrap_admin_force_takes_over_an_active_admin(user_factory):
    """The other lockout with no way back: the admin account is fine but nobody knows its
    password (the temp password's 7-day expiry lapsed, say). The idempotence check refuses on
    sight, so ``--force`` has to bypass it too, not just the username clash.
    """
    admin = user_factory(username="admin", is_staff=True, is_superuser=True)
    stdout = io.StringIO()

    call_command("bootstrap_admin", "--force", stdout=stdout)

    user_model = get_user_model()
    assert user_model.objects.count() == 1
    admin.refresh_from_db()
    assert admin.must_change_password is True
    assert "Reset admin user" in stdout.getvalue()


def test_bootstrap_admin_force_promotes_the_account_holding_the_username(user_factory):
    """A non-admin holding the name is the third clash ``--force`` is documented to resolve.

    Promoting rather than failing keeps the flag's meaning single: "make this username a
    usable admin". Nothing is promoted without ``--force`` —
    ``test_bootstrap_admin_reports_username_clash`` pins the refusal.
    """
    ordinary = user_factory(username="admin", is_staff=False, is_superuser=False)

    call_command("bootstrap_admin", "--force", stdout=io.StringIO())

    ordinary.refresh_from_db()
    assert ordinary.is_superuser is True
    assert ordinary.is_staff is True
    assert ordinary.must_change_password is True
    assert get_user_model().objects.count() == 1


def test_bootstrap_admin_force_still_validates_the_username():
    """``--force`` skips the *idempotence* check, not the input validation that stops an
    unreachable superuser being created.
    """
    with pytest.raises(CommandError, match="Invalid --username"):
        call_command("bootstrap_admin", "--force", "--username", "", stdout=io.StringIO())

    assert not get_user_model().objects.exists()


@pytest.mark.django_db(transaction=True)
def test_bootstrap_admin_force_rolls_back_the_grants_when_the_reset_fails(user_factory):
    """``_reset``'s flag grants and its temp password are one unit of work: if issuing the
    password fails, the account must not be left promoted.

    Without ``transaction.atomic()`` around the two, a failure inside ``set_temp_password``
    rolls back only that service's own writes — the ``is_active``/``is_staff``/``is_superuser``
    grants written just before it stay committed. That is exactly the state the command's
    docstring rules out: a reactivated superuser whose temp password nobody was ever shown,
    and which the *un*-forced idempotence check would then treat as "an admin already exists",
    refusing every retry.

    Needs ``transaction=True``: with the suite's usual per-test transaction the grants would be
    rolled back by the test teardown regardless, so the command's own atomicity would not be
    what the assertions below observe.
    """
    user_factory(username="admin", is_staff=False, is_superuser=False, is_active=False)

    with (
        patch(
            "accounts.services.Token.objects.filter",
            side_effect=RuntimeError("simulated token delete failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        call_command("bootstrap_admin", "--force", stdout=io.StringIO())

    reloaded = get_user_model().objects.get(username="admin")
    assert reloaded.is_active is False
    assert reloaded.is_staff is False
    assert reloaded.is_superuser is False
