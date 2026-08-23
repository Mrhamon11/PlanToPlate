#!/usr/bin/env bash
# Container entrypoint. Every step through collectstatic is idempotent and safe to run on
# every boot; each first-run command (seed_catalog, bootstrap_admin) has its own marker in
# the data volume, written only after that command actually runs, so each one runs exactly
# once whenever it eventually ships — a command that doesn't exist yet at boot time records
# nothing, and gets picked up automatically once its task lands and the image is rebuilt.
# The final `exec gunicorn` is what makes `docker compose stop` a graceful shutdown instead
# of a force-kill: without it this shell (not gunicorn) is PID 1, gunicorn never sees
# SIGTERM, and Compose kills it outright after the stop timeout — which on SQLite risks
# stopping mid-write.
set -euo pipefail

DATA_DIR="${DATA_DIR:-/app/data}"

log() {
    echo "[entrypoint] $*"
}

wait_for_database() {
    log "Waiting for the database to be reachable..."
    python - <<'PY'
import sys
import time

import django

django.setup()

from django.db import connections
from django.db.utils import OperationalError

conn = connections["default"]
deadline = time.monotonic() + 30
while True:
    try:
        conn.cursor()
        break
    except OperationalError as exc:
        if time.monotonic() >= deadline:
            print(f"Database not reachable after 30s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY
    log "Database is reachable."
}

# Checks Django's own command registry rather than pattern-matching stderr text, so this
# stays correct across Django versions and cannot be confused by an unrelated error message
# that happens to contain the word "Unknown".
management_command_exists() {
    python - "$1" <<'PY'
import sys

import django

django.setup()

from django.core.management import get_commands

sys.exit(0 if sys.argv[1] in get_commands() else 1)
PY
}

# Each command gets its own marker, written only after the command actually runs:
#   - marker already present  → this command has run before; skip it, record nothing new.
#   - command doesn't exist yet (its task hasn't shipped) → skip with a clear log line,
#     write no marker, so it runs automatically the first boot after it does exist.
#   - command exists and runs → mark it done. A command that exists and fails is a real
#     error and must abort startup — `set -e` takes care of that since this function does
#     not catch `python manage.py`'s exit status itself, and the marker is only touched on
#     the line after a successful run, so a failure never gets recorded as done.
run_first_run_command_if_present() {
    local command_name="$1"
    local marker_path="${DATA_DIR}/.ran-${command_name}"

    if [ -f "$marker_path" ]; then
        log "First-run command '${command_name}' already recorded done — skipping."
        return
    fi

    if management_command_exists "$command_name"; then
        log "Running first-run command: ${command_name}"
        python manage.py "$command_name"
        touch "$marker_path"
        log "First-run command '${command_name}' complete; marker written to ${marker_path}."
    else
        log "Skipping first-run command '${command_name}': management command not implemented yet."
    fi
}

wait_for_database

log "Applying database migrations..."
python manage.py migrate --noinput

log "Collecting static files..."
python manage.py collectstatic --noinput

mkdir -p "$DATA_DIR"
run_first_run_command_if_present seed_catalog
run_first_run_command_if_present bootstrap_admin

log "Starting gunicorn."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --access-logfile - \
    --error-logfile -
