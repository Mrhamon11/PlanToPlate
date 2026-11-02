#!/usr/bin/env bash
# SQLite backup pipeline (10.11 / 10.12, ../Plan/10-Security-And-Deployment/design.md
# "Backups — the part that actually matters").
#
# Produces, in one run:
#   1. A checksummed, gzipped snapshot of the live SQLite database, taken with SQLite's own
#      Online Backup API — the only correct way to copy a *live*, WAL-mode database. `cp` (or
#      any other byte-for-byte file copy) on a WAL database can capture a torn, inconsistent
#      state that opens fine and fails only when you actually need it — see
#      https://www.sqlite.org/backup.html. Rotated into hourly/daily/weekly tiers and pruned.
#   2. A nightly `manage.py dumpdata` JSON export — engine-independent insurance that survives
#      a SQLite version problem and doubles as the Postgres migration path (10.12).
#   3. An optional off-box sync (rclone or rsync) of the whole backup directory — a backup on
#      the same disk as the database it backs up is not a backup.
#
# Uses Python's built-in `sqlite3` module for the actual backup step rather than shelling out
# to the `sqlite3` CLI binary: `sqlite3.Connection.backup()` is the same SQLite Online Backup
# API the CLI's `.backup` dot-command wraps (https://docs.python.org/3/library/sqlite3.html
# #sqlite3.Connection.backup) — identical safety guarantee, zero new OS package to install in
# the container or on a bare VPS (the CLI binary ships in neither today). `python3` is always
#
# This script never writes to $DB_PATH — the backup step only ever reads it (via the Online
# Backup API above), and the dumpdata/off-box steps don't touch it either. That makes it safe
# to run against a real, live database without CLAUDE.md's §2 "mutates the database" permission
# gate. deploy/restore-test.sh is likewise read-only against the live database (it restores
# into its own fresh scratch directory and only ever migrates/inspects that copy). What *does*
# write to a live db.sqlite3, and needs a scratch copy or explicit permission first, is an
# actual production restore — replacing the running database with a backup, per the "Restoring
# a backup" procedure in docs/OPERATIONS.md.
# present wherever this app runs at all.
#
# Usage: deploy/backup.sh [--skip-dumpdata] [--skip-offbox-sync] [--prune-only]
set -euo pipefail

log() {
    echo "[backup] $*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(dirname "$SCRIPT_DIR")}"

DATA_DIR="${DATA_DIR:-/app/data}"
DB_PATH="${DB_PATH:-$DATA_DIR/db.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
DUMPDATA_DIR="${DUMPDATA_DIR:-$BACKUP_DIR/dumpdata}"

HOURLY_RETENTION_MINUTES="${HOURLY_RETENTION_MINUTES:-1440}"   # 24 hours
DAILY_RETENTION_DAYS="${DAILY_RETENTION_DAYS:-30}"
WEEKLY_RETENTION_DAYS="${WEEKLY_RETENTION_DAYS:-365}"
DUMPDATA_RETENTION_DAYS="${DUMPDATA_RETENTION_DAYS:-30}"

SKIP_DUMPDATA=0
SKIP_OFFBOX_SYNC=0
PRUNE_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --skip-dumpdata) SKIP_DUMPDATA=1 ;;
        --skip-offbox-sync) SKIP_OFFBOX_SYNC=1 ;;
        --prune-only) PRUNE_ONLY=1 ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--skip-dumpdata] [--skip-offbox-sync] [--prune-only]" >&2
            exit 1
            ;;
    esac
done

# Deletes files older than a retention window (mtime-based) from one tier directory, along
# with their checksum sidecar — a `.sha256` file left behind for an already-deleted backup is
# a trap for whoever runs `sha256sum -c` against it next.
prune_tier() {
    local dir="$1"
    local find_age_flag="$2"   # e.g. "-mmin +1440" or "-mtime +30", pre-split on the caller
    local find_age_value="$3"

    [ -d "$dir" ] || return 0

    find "$dir" -maxdepth 1 -type f -name '*.sqlite3.gz' "$find_age_flag" "$find_age_value" -print0 |
        while IFS= read -r -d '' stale; do
            log "Pruning expired backup: $stale"
            rm -f -- "$stale" "$stale.sha256"
        done
}

prune_all_tiers() {
    log "Pruning expired backups (hourly > ${HOURLY_RETENTION_MINUTES}m, daily > ${DAILY_RETENTION_DAYS}d, weekly > ${WEEKLY_RETENTION_DAYS}d)."
    prune_tier "$BACKUP_DIR/hourly" -mmin "+${HOURLY_RETENTION_MINUTES}"
    prune_tier "$BACKUP_DIR/daily" -mtime "+${DAILY_RETENTION_DAYS}"
    prune_tier "$BACKUP_DIR/weekly" -mtime "+${WEEKLY_RETENTION_DAYS}"

    if [ -d "$DUMPDATA_DIR" ]; then
        find "$DUMPDATA_DIR" -maxdepth 1 -type f -name '*.json.gz' -mtime "+${DUMPDATA_RETENTION_DAYS}" -print0 |
            while IFS= read -r -d '' stale; do
                log "Pruning expired dumpdata export: $stale"
                rm -f -- "$stale" "$stale.sha256"
            done
    fi
}

if [ "$PRUNE_ONLY" -eq 1 ]; then
    prune_all_tiers
    exit 0
fi

mkdir -p "$BACKUP_DIR/hourly" "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"

if [ ! -f "$DB_PATH" ]; then
    echo "backup.sh: no database at $DB_PATH" >&2
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
day_key="$(date -u +%Y-%m-%d)"
week_key="$(date -u +%G-W%V)"

stem="plantoplate-${timestamp}.sqlite3"
tmp_backup="$(mktemp "${TMPDIR:-/tmp}/${stem}.XXXXXX")"
trap 'rm -f "$tmp_backup"' EXIT

log "Backing up $DB_PATH via SQLite's Online Backup API..."
python3 - "$DB_PATH" "$tmp_backup" <<'PY'
import sqlite3
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
try:
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
finally:
    src.close()
PY

log "Verifying backup integrity..."
integrity="$(python3 - "$tmp_backup" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
print(conn.execute("PRAGMA integrity_check;").fetchone()[0])
conn.close()
PY
)"
if [ "$integrity" != "ok" ]; then
    echo "backup.sh: integrity check failed: $integrity" >&2
    exit 1
fi

# Bare filename in the sidecar, not the absolute path: the file is copied off-box and
# verified from wherever it lands, where the original directory does not exist.
write_checksum() {
    (cd "$(dirname "$1")" && sha256sum "$(basename "$1")" > "$(basename "$1").sha256")
}

hourly_file="$BACKUP_DIR/hourly/${stem}.gz"
gzip -c "$tmp_backup" > "$hourly_file"
write_checksum "$hourly_file"
log "Wrote $hourly_file (checksummed)."

daily_file="$BACKUP_DIR/daily/plantoplate-${day_key}.sqlite3.gz"
if [ ! -e "$daily_file" ]; then
    ln "$hourly_file" "$daily_file" 2>/dev/null || cp "$hourly_file" "$daily_file"
    write_checksum "$daily_file"
    log "Promoted today's backup to $daily_file."
fi

weekly_file="$BACKUP_DIR/weekly/plantoplate-${week_key}.sqlite3.gz"
if [ ! -e "$weekly_file" ]; then
    ln "$hourly_file" "$weekly_file" 2>/dev/null || cp "$hourly_file" "$weekly_file"
    write_checksum "$weekly_file"
    log "Promoted this week's backup to $weekly_file."
fi

if [ "$SKIP_DUMPDATA" -eq 0 ]; then
    log "Exporting engine-independent dumpdata JSON (10.12)..."
    mkdir -p "$DUMPDATA_DIR"
    dump_tmp="$(mktemp "${TMPDIR:-/tmp}/plantoplate-dumpdata.XXXXXX.json")"
    (
        cd "$APP_DIR"
        python3 manage.py dumpdata \
            --natural-foreign --natural-primary \
            --exclude contenttypes --exclude auth.permission --exclude sessions \
            --indent 2 > "$dump_tmp"
    )
    dump_file="$DUMPDATA_DIR/plantoplate-${timestamp}.json.gz"
    gzip -c "$dump_tmp" > "$dump_file"
    write_checksum "$dump_file"
    rm -f "$dump_tmp"
    log "Wrote $dump_file (checksummed)."
else
    log "Skipping dumpdata export (--skip-dumpdata)."
fi

prune_all_tiers

if [ "$SKIP_OFFBOX_SYNC" -eq 0 ]; then
    if [ -n "${RCLONE_REMOTE:-}" ]; then
        if ! command -v rclone >/dev/null 2>&1; then
            log "ERROR: RCLONE_REMOTE is set but rclone is not installed here; nothing was copied off-box."
            exit 1
        fi
        log "Syncing $BACKUP_DIR to $RCLONE_REMOTE via rclone..."
        rclone sync "$BACKUP_DIR" "$RCLONE_REMOTE"
    elif [ -n "${RSYNC_TARGET:-}" ]; then
        if ! command -v rsync >/dev/null 2>&1; then
            log "ERROR: RSYNC_TARGET is set but rsync is not installed here; nothing was copied off-box."
            exit 1
        fi
        log "Syncing $BACKUP_DIR to $RSYNC_TARGET via rsync..."
        rsync -az --delete "$BACKUP_DIR/" "$RSYNC_TARGET"
    else
        log "No off-box sync configured (set RCLONE_REMOTE or RSYNC_TARGET) — skipping."
    fi
else
    log "Skipping off-box sync (--skip-offbox-sync)."
fi

log "Backup complete."
