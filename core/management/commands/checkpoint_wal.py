"""``manage.py checkpoint_wal`` — periodic WAL maintenance (10.14,
``Plan/10-Security-And-Deployment/design.md``, "Edge cases": "WAL growing unboundedly under a
long read: periodic ``wal_checkpoint(TRUNCATE)``").

``config/settings/base.py``'s ``SQLITE_OPTIONS`` already puts every connection in WAL mode
(``PRAGMA journal_mode=WAL``) for the concurrency benefits MILESTONES.md section 2 describes,
but WAL mode's trade-off is that the write-ahead log file grows until something checkpoints it
— SQLite auto-checkpoints at a page threshold, but a long-running read transaction can hold
that off indefinitely, and the auto-checkpoint alone does not *truncate* the WAL file back to
zero bytes. Run this periodically (a systemd timer or cron entry — see
``docs/OPERATIONS.md``) to fold the WAL back into the main database file and reclaim the disk
space.

Thin over ``core.services.wal.checkpoint_truncate`` — see that module's docstring for why the
actual checkpoint runs through an independent connection rather than Django's own.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import connections

from core.services.wal import checkpoint_truncate


class Command(BaseCommand):
    help = (
        "Runs PRAGMA wal_checkpoint(TRUNCATE) against a SQLite database, folding its "
        "write-ahead log back into the main database file and truncating it to zero bytes. "
        "A no-op (not an error) against a non-SQLite engine."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--database",
            default="default",
            help="Which configured database alias to checkpoint (default: 'default').",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        alias = options["database"]
        connection = connections[alias]

        if connection.vendor != "sqlite":
            self.stdout.write(
                self.style.WARNING(
                    f"checkpoint_wal: database '{alias}' is {connection.vendor}, not SQLite — "
                    "nothing to do."
                )
            )
            return

        result = checkpoint_truncate(connection.settings_dict["NAME"])

        if result.busy:
            # A concurrent writer held a lock the checkpoint needed — expected under real
            # traffic, not a failure worth aborting a cron job over. The WAL still shrank by
            # whatever frames it managed to checkpoint; the next scheduled run picks up the rest.
            self.stdout.write(
                self.style.WARNING(
                    "checkpoint_wal: could not fully checkpoint (a writer held the database "
                    f"busy) — checkpointed {result.checkpointed_frames} of "
                    f"{result.log_frames} frames. Safe to retry."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"checkpoint_wal: checkpointed {result.checkpointed_frames} frames, WAL truncated."
            )
        )
