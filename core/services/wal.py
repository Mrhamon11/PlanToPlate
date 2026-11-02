"""SQLite WAL checkpoint maintenance (10.14, ``Plan/10-Security-And-Deployment/design.md``,
"Edge cases": "WAL growing unboundedly under a long read: periodic
``wal_checkpoint(TRUNCATE)``").

Used by ``core.management.commands.checkpoint_wal``. Deliberately operates through a fresh,
independent ``sqlite3.connect()`` rather than Django's own ``connection``/cursor machinery for
the configured alias: the checkpoint is a maintenance action against the database *file*, not
a query that needs Django's connection pooling, transaction state, or ORM layer, and issuing it
through a separate connection means it can never disturb whatever transaction Django's own
long-lived connection for that alias happens to be mid-way through.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class WalCheckpointResult:
    #: ``True`` if a concurrent writer held a lock the checkpoint needed — SQLite could not
    #: fully checkpoint (and did not truncate), but this is an expected, retry-safe condition
    #: under real traffic, not a failure.
    busy: bool
    #: Total frames in the WAL file at the time of the checkpoint.
    log_frames: int
    #: How many of those frames were actually checkpointed into the main database file.
    checkpointed_frames: int


def checkpoint_truncate(db_path: str) -> WalCheckpointResult:
    """Runs ``PRAGMA wal_checkpoint(TRUNCATE)`` against the SQLite file at ``db_path``,
    folding its write-ahead log back into the main database file and truncating the WAL file
    to zero bytes (when not ``busy``).
    """
    conn = sqlite3.connect(db_path)
    try:
        busy, log_frames, checkpointed_frames = conn.execute(
            "PRAGMA wal_checkpoint(TRUNCATE);"
        ).fetchone()
    finally:
        conn.close()
    return WalCheckpointResult(bool(busy), log_frames, checkpointed_frames)
