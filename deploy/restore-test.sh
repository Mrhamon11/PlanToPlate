#!/usr/bin/env bash
# The restore drill (10.13, ../Plan/10-Security-And-Deployment/design.md "Restore drill" —
# "A backup that has never been restored is a hypothesis."). Restores the most recent (or an
# explicitly named) backup into a fresh scratch directory, runs `manage.py migrate` against it
# (the realistic disaster path is "restore, then migrate" — design.md's "Edge cases"), and
# compares every table's row count against the live source database. Exits nonzero, and prints
# exactly which table diverged, on any mismatch.
#
# Usage: deploy/restore-test.sh [BACKUP_FILE]
#   BACKUP_FILE  A specific *.sqlite3.gz backup. Defaults to the newest file under
#                $BACKUP_DIR/hourly.
#
# Reads the same DATA_DIR / DB_PATH / BACKUP_DIR environment variables as backup.sh, plus:
#   SCRATCH_DIR  Where to restore into. Defaults to a fresh `mktemp -d` (removed on exit unless
#                KEEP_SCRATCH=1).
set -euo pipefail

log() {
    echo "[restore-test] $*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(dirname "$SCRIPT_DIR")}"

DATA_DIR="${DATA_DIR:-/app/data}"
DB_PATH="${DB_PATH:-$DATA_DIR/db.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"

BACKUP_FILE="${1:-}"
if [ -z "$BACKUP_FILE" ]; then
    BACKUP_FILE="$(find "$BACKUP_DIR/hourly" -maxdepth 1 -type f -name '*.sqlite3.gz' -printf '%T@ %p\n' 2>/dev/null |
        sort -rn | head -n1 | cut -d' ' -f2-)"
fi
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "restore-test.sh: no backup file found (looked under $BACKUP_DIR/hourly)" >&2
    exit 1
fi
if [ ! -f "$DB_PATH" ]; then
    echo "restore-test.sh: no live database at $DB_PATH to compare against" >&2
    exit 1
fi

SCRATCH_DIR="${SCRATCH_DIR:-$(mktemp -d)}"
mkdir -p "$SCRATCH_DIR"
if [ "${KEEP_SCRATCH:-0}" -ne 1 ]; then
    trap 'rm -rf "$SCRATCH_DIR"' EXIT
fi

log "Restoring $BACKUP_FILE into scratch directory $SCRATCH_DIR..."

if [ -f "$BACKUP_FILE.sha256" ]; then
    log "Verifying checksum..."
    (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
else
    echo "restore-test.sh: WARNING no checksum sidecar for $BACKUP_FILE — restoring unverified." >&2
fi

restored_db="$SCRATCH_DIR/restored.sqlite3"
gunzip -c "$BACKUP_FILE" > "$restored_db"

log "Checking restored database integrity..."
integrity="$(python3 -c "
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
print(conn.execute('PRAGMA integrity_check;').fetchone()[0])
conn.close()
" "$restored_db")"
if [ "$integrity" != "ok" ]; then
    echo "restore-test.sh: restored database failed integrity check: $integrity" >&2
    exit 1
fi

log "Restore, then migrate (design.md's edge case: that order, not the reverse)..."
(
    cd "$APP_DIR"
    DATABASE_URL="sqlite:////${restored_db#/}" python3 manage.py migrate --noinput
)

log "Comparing every table's row count against the live source..."
# The Python side always exits 0 and encodes pass/fail purely in its final "RESULT" line — a
# nonzero exit from this command substitution, under `set -e`, would abort the script *before*
# `report` is ever assigned or echoed, silently swallowing the very report this step exists to
# print. The `grep` below is what actually decides this script's own exit status.
report="$(python3 -c "
import sqlite3, sys

source_path, restored_path = sys.argv[1], sys.argv[2]
source = sqlite3.connect(source_path)
restored = sqlite3.connect(restored_path)

# django_migrations is Django's own bookkeeping, not application data, and this step's whole
# point is 'restore, then migrate' (design.md's edge case) -- a backup taken before a migration
# that has since landed on disk will legitimately gain rows there that the live source, if it
# has not been migrated forward too, does not have yet. Diverging here is what a *correct*
# restore-then-migrate looks like, not a data-loss signal, so it is excluded from the row-count
# comparison this drill is actually checking: every table of real application data.
tables = [
    row[0]
    for row in source.execute(
        \"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\"
    )
    if row[0] != 'django_migrations'
]

mismatches = []
for table in sorted(tables):
    source_count = source.execute(f'SELECT COUNT(*) FROM \"{table}\"').fetchone()[0]
    try:
        restored_count = restored.execute(f'SELECT COUNT(*) FROM \"{table}\"').fetchone()[0]
    except sqlite3.OperationalError:
        restored_count = None
    status = 'OK' if source_count == restored_count else 'MISMATCH'
    print(f'{status:8} {table:40} source={source_count} restored={restored_count}')
    if status == 'MISMATCH':
        mismatches.append(table)

source.close()
restored.close()

if mismatches:
    print(f'RESULT FAIL -- {len(mismatches)} table(s) diverged: {\", \".join(mismatches)}')
else:
    print('RESULT PASS -- every table matches the live source.')
" "$DB_PATH" "$restored_db")"

echo "$report"
if echo "$report" | grep -q '^RESULT PASS'; then
    log "Restore drill PASSED."
    exit 0
else
    log "Restore drill FAILED — see mismatches above."
    exit 1
fi
