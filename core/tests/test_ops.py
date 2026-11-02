"""Health and operations commands (10.14/10.15 —
``Plan/10-Security-And-Deployment/test-plan.md``).

``checkpoint_wal`` (10.14) and ``test_logging_excludes_passwords`` (10.15) are covered here —
``test_healthz_reports_db`` (task 00) already lives in ``core/tests/test_views.py``.

The two ``checkpoint_wal`` tests need no database access (no ``django_db`` marker): the command
reads a connection's ``vendor``/``settings_dict`` — plain attributes, not a live query — and the
actual checkpoint runs through ``core.services.wal.checkpoint_truncate``'s own independent
``sqlite3.connect()``, never Django's connection/cursor machinery. That sidesteps a real trap:
``config.settings.test`` backs the ``"default"`` alias with ``:memory:``, and an in-memory
SQLite database lives only as long as the one connection that created it — closing or
repointing that connection (which checkpointing a different file through Django's own
connection object would require) destroys the schema for the rest of the test session.
"""

from __future__ import annotations

import logging
import logging.handlers
import sqlite3
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connections
from django.urls import reverse

from config.settings.prod import _logging_config


def _forget_alias(alias: str) -> None:
    """Undoes registering a throwaway database alias: the command's ``connections[alias]``
    lookup caches a ``DatabaseWrapper`` in ``connections``' thread-local storage as a side
    effect (even though this project's ``checkpoint_wal`` never actually connects through it —
    see the module docstring), so both that cache entry and the settings-dict entry need
    clearing, or a later test reusing the same alias name could see stale state.
    """
    try:
        del connections[alias]
    except AttributeError:
        pass
    del connections.databases[alias]


def test_checkpoint_wal_command(tmp_path, capsys):
    """Runs and shrinks the WAL: against a real file-based SQLite database in WAL mode with
    an un-checkpointed write-ahead log, the command truncates the WAL file back down.
    """
    db_path = tmp_path / "wal-scratch.sqlite3"
    # Deliberately left open for the rest of the test: closing the only connection to a WAL
    # database triggers SQLite's own auto-checkpoint-on-close, which would zero (and then
    # delete) the WAL file before the command ever runs, defeating the point of this test. The
    # command checkpoints through its own, separate connection — exactly the normal
    # multi-connection use of WAL mode.
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA journal_mode=WAL;")
        raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        raw.executemany("INSERT INTO t (v) VALUES (?)", [(f"row-{i}",) for i in range(500)])
        raw.commit()

        wal_path = db_path.with_name(db_path.name + "-wal")
        assert wal_path.is_file(), "a WAL file should exist after a WAL-mode write"
        wal_size_before = wal_path.stat().st_size
        assert wal_size_before > 0

        # A throwaway alias pointed at the scratch file — never "default", never touched by
        # pytest-django's database machinery, since the command only reads its `vendor` /
        # `settings_dict["NAME"]` (plain attributes) and checkpoints via a fully independent
        # connection, not this wrapper's own `.cursor()`.
        connections.databases["wal_scratch"] = {
            **connections.databases["default"],
            "NAME": str(db_path),
        }
        try:
            call_command("checkpoint_wal", database="wal_scratch")
        finally:
            _forget_alias("wal_scratch")

        assert wal_path.stat().st_size < wal_size_before
        assert wal_path.stat().st_size == 0
        assert "checkpointed" in capsys.readouterr().out
    finally:
        raw.close()


def test_checkpoint_wal_command_is_a_noop_against_a_non_sqlite_alias(capsys):
    """A configured non-SQLite alias is reported and skipped, not an error — the command must
    degrade gracefully rather than assume every deployment is SQLite (MILESTONES.md's Postgres
    portability rule).
    """
    connections.databases["dummy_scratch"] = {
        **connections.databases["default"],
        "ENGINE": "django.db.backends.dummy",
    }
    try:
        call_command("checkpoint_wal", database="dummy_scratch")
    finally:
        _forget_alias("dummy_scratch")

    assert "not SQLite" in capsys.readouterr().out


@pytest.mark.django_db
def test_logging_excludes_passwords(tmp_path, client, user_factory):
    """10.15: an auth request writes no credential to any handler — verified against the real
    rotating file handlers ``config.settings.prod._logging_config`` builds, not only against
    ``caplog``'s generic in-process capture (``accounts/tests/test_security.py
    ::test_password_not_in_logs`` already covers that half). The whole point of a *file*-backed
    handler is that a secret must not land in a file gunicorn/production actually writes to.

    Attaches the two handler instances directly to the ``"django"`` logger for the duration of
    this test — rather than a full ``logging.config.dictConfig(...)`` — so no other logger's
    configuration (or the rest of the test session's) is disturbed; the previous handlers/level
    are restored in every case, including a failure partway through.
    """
    logging_config = _logging_config(tmp_path)
    app_settings = logging_config["handlers"]["app_file"]
    error_settings = logging_config["handlers"]["error_file"]

    app_handler = logging.handlers.RotatingFileHandler(
        filename=app_settings["filename"],
        maxBytes=app_settings["maxBytes"],
        backupCount=app_settings["backupCount"],
    )
    error_handler = logging.handlers.RotatingFileHandler(
        filename=error_settings["filename"],
        maxBytes=error_settings["maxBytes"],
        backupCount=error_settings["backupCount"],
    )
    error_handler.setLevel(logging.ERROR)

    django_logger = logging.getLogger("django")
    saved_handlers = django_logger.handlers[:]
    saved_level = django_logger.level

    django_logger.handlers = [app_handler, error_handler]
    django_logger.setLevel(logging.DEBUG)
    try:
        plain_password = "correct-horse-battery-staple"
        user = user_factory(password=plain_password)

        client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": plain_password},
        )
        client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": "definitely-the-wrong-password"},
        )
    finally:
        django_logger.handlers = saved_handlers
        django_logger.setLevel(saved_level)
        app_handler.close()
        error_handler.close()

    for filename in (app_settings["filename"], error_settings["filename"]):
        content = Path(filename).read_text(encoding="utf-8")
        assert plain_password not in content
        assert "definitely-the-wrong-password" not in content
