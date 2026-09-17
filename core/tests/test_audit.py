"""Audit trail for the admin's custom actions (task 09.13, user-management half pulled
forward — see ``core/services/audit.py``).
"""

from __future__ import annotations

import json

import pytest
from django.contrib.admin.models import LogEntry

from accounts import services
from core.services import audit
from core.services.importer import run_import

pytestmark = pytest.mark.django_db


def _import_file() -> str:
    return json.dumps(
        {
            "version": 1,
            "ingredients": [{"name": "Flour", "default_unit": "g"}],
            "recipes": [
                {
                    "name": "Bread",
                    "yield_quantity": "1",
                    "yield_unit": "cup",
                    "instructions": "Bake.",
                    "components": [{"ingredient": "Flour", "quantity": "500", "unit": "g"}],
                }
            ],
            "dishes": [{"name": "Bread plate", "recipes": ["Bread"]}],
        }
    )


@pytest.fixture
def admin_user(user_factory):
    return user_factory(username="auditadmin", is_staff=True, is_superuser=True)


def test_temp_password_issue_logged(admin_user):
    user, _temp = services.create_user(actor=admin_user, username="issued")

    entries = LogEntry.objects.filter(object_id=str(user.pk))
    assert any(e.change_message.startswith(audit.TEMP_PASSWORD_ISSUED) for e in entries)
    reset_actor = admin_user
    services.reset_password(actor=reset_actor, user=user)
    assert (
        LogEntry.objects.filter(
            object_id=str(user.pk), change_message__contains="admin reset"
        ).count()
        == 1
    )


def test_entitlement_change_logged(admin_user, user_factory):
    keeper = user_factory(username="keeper", is_staff=True)  # noqa: F841 — keeps an admin
    target = user_factory(username="entitled", is_staff=False)

    services.set_entitlement(actor=admin_user, user=target, is_staff=True)
    services.set_entitlement(actor=admin_user, user=target, is_staff=False)

    messages = [e.change_message for e in LogEntry.objects.filter(object_id=str(target.pk))]
    assert audit.ADMIN_ACCESS_GRANTED in messages
    assert audit.ADMIN_ACCESS_REVOKED in messages


def test_no_op_entitlement_change_not_logged(admin_user, user_factory):
    target = user_factory(username="already", is_staff=False)
    changed = services.set_entitlement(actor=admin_user, user=target, is_staff=False)
    assert changed is False
    assert not LogEntry.objects.filter(object_id=str(target.pk)).exists()


def test_import_logged(admin_user, alice, gram, cup):
    """A bulk import writes one audit record naming the per-section object counts — and
    nothing from the file's contents (design.md, "Audit trail").
    """
    run_import(raw=_import_file(), owner=alice, actor=admin_user, dry_run=False)

    entries = LogEntry.objects.filter(
        object_id=str(alice.pk), change_message__startswith=audit.BULK_IMPORT_RUN
    )
    assert entries.count() == 1
    message = entries.get().change_message
    assert "ingredients: 1 created" in message
    assert "recipes: 1 created" in message
    assert "dishes: 1 created" in message
    # The record carries counts only — no imported object names.
    assert "Flour" not in message
    assert "Bread" not in message


def test_dry_run_import_not_logged(admin_user, alice, gram, cup):
    """A dry run writes nothing — including no audit record."""
    run_import(raw=_import_file(), owner=alice, actor=admin_user, dry_run=True)
    assert not LogEntry.objects.filter(change_message__startswith=audit.BULK_IMPORT_RUN).exists()


def test_no_password_in_any_log_entry(admin_user, user_factory, alice, gram, cup):
    """Every custom-action ``LogEntry`` message and repr is scanned — the plaintext temp
    password must appear in none of them. The bulk-import record is in scope too.
    """
    _u1, temp1 = services.create_user(actor=admin_user, username="scan1")
    target = user_factory(username="scan2")
    temp2 = services.reset_password(actor=admin_user, user=target)
    run_import(raw=_import_file(), owner=alice, actor=admin_user, dry_run=False)

    assert LogEntry.objects.filter(change_message__startswith=audit.BULK_IMPORT_RUN).exists()

    secrets_shown = {temp1, temp2}
    for entry in LogEntry.objects.all():
        for secret in secrets_shown:
            assert secret not in entry.change_message
            assert secret not in entry.object_repr
