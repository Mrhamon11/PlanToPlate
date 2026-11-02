#!/usr/bin/env bash
# Docker Compose backup, run from the HOST (cron or a systemd timer).
#
# The app image carries no rsync, rclone or ssh, so the container cannot copy backups off-box
# itself. This script takes the backup inside the container (--skip-offbox-sync), copies the
# backup directory out to the host, then syncs it with the host's own tools and SSH keys.
#
# Environment:
#   COMPOSE_FILE_ARGS   compose -f arguments (default: "-f compose.prod.yaml")
#   RSYNC_TARGET        e.g. user@otherhost:/backups/plantoplate/
#   RCLONE_REMOTE       e.g. myremote:plantoplate-backups
#   STAGING_DIR         host directory the backups are copied to (default: ./backups-offbox)
#
# RSYNC_TARGET / RCLONE_REMOTE are read from the environment, or failing that from this
# directory's .env (the same file the container reads), so one setting serves both.
#
# With neither target set the backup still happens inside the container and this script says
# plainly that nothing left the machine. A set target whose tool is missing is an error.

set -euo pipefail

# The staging copy is a whole database, password hashes included.
umask 077

COMPOSE_FILE_ARGS="${COMPOSE_FILE_ARGS:--f compose.prod.yaml}"
STAGING_DIR="${STAGING_DIR:-./backups-offbox}"

log() { printf '[docker-backup] %s\n' "$*"; }

env_file_value() {
    [ -f .env ] || return 0
    grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" || true
}

RSYNC_TARGET="${RSYNC_TARGET:-$(env_file_value RSYNC_TARGET)}"
RCLONE_REMOTE="${RCLONE_REMOTE:-$(env_file_value RCLONE_REMOTE)}"

# Overlapping runs would race on the staging directory.
if command -v flock >/dev/null 2>&1; then
    exec 9>"${LOCK_FILE:-${TMPDIR:-/tmp}/plantoplate-docker-backup.lock}"
    flock -n 9 || { log "Another run is in progress; exiting."; exit 0; }
fi

# STAGING_DIR is deleted and recreated on every run, so refuse anything that is not empty or
# plainly a previous staging copy. Pointing it at /, $HOME or a project directory must not be
# able to wipe it.
check_staging_dir() {
    [ -n "$STAGING_DIR" ] || { log "ERROR: STAGING_DIR is empty."; exit 1; }
    [ -d "$STAGING_DIR" ] || return 0
    local entry name
    for entry in "$STAGING_DIR"/* "$STAGING_DIR"/.[!.]*; do
        [ -e "$entry" ] || continue
        name="$(basename "$entry")"
        case "$name" in
            hourly|daily|weekly|dumpdata) ;;
            *) log "ERROR: $STAGING_DIR contains '$name', which is not a backup tier; refusing to delete it."; exit 1 ;;
        esac
    done
}

# shellcheck disable=SC2086 # COMPOSE_FILE_ARGS is deliberately word-split into -f arguments
compose() { docker compose $COMPOSE_FILE_ARGS "$@"; }

compose exec -T app deploy/backup.sh --skip-offbox-sync

if [ -z "${RSYNC_TARGET:-}" ] && [ -z "${RCLONE_REMOTE:-}" ]; then
    log "No off-box target set (RSYNC_TARGET or RCLONE_REMOTE): backups exist only on this machine."
    exit 0
fi

if [ -n "${RCLONE_REMOTE:-}" ]; then
    command -v rclone >/dev/null 2>&1 || { log "ERROR: RCLONE_REMOTE is set but rclone is not installed."; exit 1; }
else
    command -v rsync >/dev/null 2>&1 || { log "ERROR: RSYNC_TARGET is set but rsync is not installed."; exit 1; }
fi

check_staging_dir
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
compose cp app:/app/data/backups/. "$STAGING_DIR"

if [ -n "${RCLONE_REMOTE:-}" ]; then
    log "Syncing $STAGING_DIR to $RCLONE_REMOTE via rclone..."
    rclone sync "$STAGING_DIR" "$RCLONE_REMOTE"
else
    log "Syncing $STAGING_DIR to $RSYNC_TARGET via rsync..."
    rsync -az --delete "$STAGING_DIR/" "$RSYNC_TARGET"
fi

log "Off-box sync complete."
