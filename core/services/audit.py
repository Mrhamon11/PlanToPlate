"""Audit trail for the admin's custom, security-sensitive actions (``Plan/09-Admin-Control-
Center/design.md``, "Audit trail").

Django's ``LogEntry`` already records ordinary admin CRUD. The flows this module logs —
issuing a temp password, changing an account's admin entitlement — do not go through a
``ModelAdmin.save_model`` and would otherwise leave no trace, and they are exactly the actions
worth reconstructing after the fact ("who reset whose password, and when").

**The password itself is never an argument here and never reaches a log record.** The design's
rule is "log *that* a password was issued, never the password." The same rule applies to the
bulk import: :func:`record_import_run` logs the per-section object *counts* and nothing from
the file's contents.

09.13 is now complete: the user-management records (temp password issued, entitlement
changed) are emitted by 09.5 / 09.6 / 09.8 and both ``bootstrap_admin`` paths; the import
record is emitted by ``core.services.importer.execute`` (so the admin page and
``manage.py import_json`` — which share ``run_import`` — both produce it).
"""

from __future__ import annotations

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType

from accounts.models import User

#: Stable change-message prefixes. Tests scan for these; keep them greppable.
TEMP_PASSWORD_ISSUED = "Temp password issued"  # noqa: S105 — a log-message label, not a secret
ADMIN_ACCESS_GRANTED = "Admin access granted (is_staff set)"
ADMIN_ACCESS_REVOKED = "Admin access revoked (is_staff cleared)"
BULK_IMPORT_RUN = "Bulk JSON import applied"

_IMPORT_SECTIONS = ("ingredients", "recipes", "dishes")


def _log(*, actor: User | None, target: User, message: str) -> LogEntry:
    """Write one ``LogEntry`` against ``target``.

    ``LogEntry.user`` is non-nullable. A shell action such as ``bootstrap_admin`` has no
    request user — it records the change against ``target`` itself, which is accurate enough
    ("this account was administered out of band") and keeps the row valid.
    """
    return LogEntry.objects.log_action(
        user_id=(actor or target).pk,
        content_type_id=ContentType.objects.get_for_model(User).pk,
        object_id=target.pk,
        object_repr=str(target),
        action_flag=CHANGE,
        change_message=message,
    )


def record_temp_password_issued(*, actor: User | None, target: User, context: str) -> LogEntry:
    """Record that a one-time temp password was issued for ``target``.

    ``context`` is a short free-text note on *why* (``"user created"``, ``"admin reset"``,
    ``"bootstrap_admin --force"``) — never the password.
    """
    return _log(actor=actor, target=target, message=f"{TEMP_PASSWORD_ISSUED}: {context}.")


def record_entitlement_change(*, actor: User | None, target: User, granted: bool) -> LogEntry:
    """Record that ``target``'s admin entitlement (``is_staff``) was granted or revoked."""
    message = ADMIN_ACCESS_GRANTED if granted else ADMIN_ACCESS_REVOKED
    return _log(actor=actor, target=target, message=message)


def record_import_run(*, actor: User | None, owner: User, report, mode: str) -> LogEntry:
    """Record *that* a bulk JSON import was applied for ``owner`` — with the per-section object
    counts, and nothing else. Never the object contents, never anything from the file itself.

    ``report`` is an ``importer.ImportReport`` (imported lazily by the caller to avoid a
    circular import). The record is written against ``owner`` — the account whose data changed.
    """
    counts = ", ".join(
        f"{section}: {report.created[section]} created, "
        f"{report.updated[section]} updated, {report.skipped[section]} skipped"
        for section in _IMPORT_SECTIONS
    )
    return _log(
        actor=actor,
        target=owner,
        message=f"{BULK_IMPORT_RUN} (mode {mode}) — {counts}.",
    )
