# Operations

> The production runbook (10.16). `README.md` covers first *local* deployment via Docker
> Compose (`compose.yaml`, dev-oriented defaults) and links here for the production path
> (`compose.prod.yaml`, hardened settings) rather than duplicating it.

## Production first deployment (Docker Compose)

This is the whole sequence for a clean server, start to finish. Every command is
copy-pasteable in order — nothing here assumes a step you haven't been told about yet.

```bash
# 1. Clone and start from the example environment file.
git clone <this repository> plantoplate
cd plantoplate
cp .env.example .env
```

```bash
# 2. Generate SECRET_KEY and paste it into .env.
make secret
# -> copy the printed value into .env's SECRET_KEY= line
```

**The app refuses to start with no `SECRET_KEY`** — there is no default, because a defaulted
secret key means forgeable sessions (D5). Generate it once and keep it: `SECRET_KEY` signs
every session cookie, so **losing it or rotating it later logs every single user out**
(design.md's "Edge cases" — expect everyone to have to log back in). Treat it like a
password: back it up with the rest of `.env` (outside the repo — `.env` is gitignored), and
never commit it.

```bash
# 3. Set the hostname(s) this deployment actually answers to, in .env.
ALLOWED_HOSTS=plantoplate.example.com
SITE_ADDRESS=plantoplate.example.com
# CSRF_TRUSTED_ORIGINS is usually left unset -- see "When you actually need
# CSRF_TRUSTED_ORIGINS" below before setting it.
```

`ALLOWED_HOSTS` is a comma-separated list; `config/settings/prod.py` always appends
`127.0.0.1` on top of whatever you list here for the Compose healthcheck, so you never add
that yourself (D20). `SITE_ADDRESS` is what Caddy provisions TLS for — leave it at
`localhost` (the `.env.example` default) for a Tailscale-only deployment (Caddy issues a
self-signed cert from its own internal CA); set it to a real, publicly resolvable domain to
get an automatic Let's Encrypt certificate instead (see README.md's "TLS" section for the
mechanics — this doc does not repeat them).

**When you actually need `CSRF_TRUSTED_ORIGINS`.** `config/settings/prod.py` leaves this
empty by default (a deliberate, documented deviation from design.md's literal
no-default setting — see `Plan/ARCHITECTURE.md`'s decision log). Leaving it unset is correct
and sufficient for the single-hostname topology this app is designed for — one Caddy instance
fronting one hostname, with `SECURE_PROXY_SSL_HEADER` already telling Django the original
request was HTTPS. You need to set it only when a POST's `Origin` header would not match
`request.get_host()` on its own — concretely:

- **A second hostname answers the same app** — e.g. a public domain *and* a Tailscale
  MagicDNS name both resolve to this deployment, and you want to use both interchangeably.
- **A reverse proxy in front of Caddy rewrites `Host`** in a way that changes what Django sees
  versus what the browser's address bar shows.

If either applies, set it to the **full origin(s)**, scheme included, comma-separated:

```bash
CSRF_TRUSTED_ORIGINS=https://plantoplate.example.com,https://plantoplate.tailnet-name.ts.net
```

Getting this wrong shows up immediately and loudly as CSRF failures on every POST (login,
every form submission) from the hostname you forgot to list — it does not fail silently.

```bash
# 4. Build and start the production stack.
make docker-build-prod
docker compose -f compose.prod.yaml up -d
```

`make docker-build-prod` stamps the image with the current commit and build time (`GIT_SHA` /
`BUILD_DATE`, D57) — visible later on the admin dashboard, the first thing to check when
diagnosing "which version is actually running." `compose.prod.yaml` layers restart policies,
resource limits, and bounded log retention on top of the same entrypoint and image
`compose.yaml` uses (10.7) — it is not a second, divergent startup path.

**If `SITE_ADDRESS` is a Tailscale name (`*.ts.net`)**, Caddy fetches its certificate from the
host's `tailscaled` over a unix socket, which the plain stack does not mount. Enable "HTTPS
Certificates" for the tailnet in the Tailscale admin console (this publishes your machine names
in public certificate-transparency logs), then start with the override:

```bash
docker compose -f compose.prod.yaml -f compose.tailscale.yaml up -d
```

Without it every TLS handshake fails (curl exit 35) and Caddy's log says it cannot reach
`tailscaled.sock`. On a SELinux-enforcing host the override also relaxes label confinement for
the Caddy container; see the comments in `compose.tailscale.yaml`.

```bash
# 5. Retrieve the admin temp password -- printed once, before logs rotate.
docker compose -f compose.prod.yaml logs app | grep -A2 "Temporary password"
```

This is the **only** place that password is ever shown. It is not stored anywhere the app can
retrieve later, and it stays readable only until the container's log history rotates
(`compose.prod.yaml` bounds this to 50 MB / 5 files — see 10.7's resolution note in
`Plan/10-Security-And-Deployment/tasks.md`) or the container is recreated. Capture it now.

```bash
# 6. Log in, complete the forced password change, verify health.
curl -k https://<your-host>/healthz/   # {"status": "ok", "database": "ok"}
```

Open `https://<your-host>/` in a browser, log in as `admin` with the temp password from step
5, and complete the forced password-change prompt — you cannot use the app until you do
(`must_change_password` blocks every other page and endpoint). Confirm `/healthz/` reports
`"database": "ok"`, not just a 200.

```bash
# 7. Run the first backup and immediately test-restore it -- before real data goes in.
docker compose -f compose.prod.yaml exec -T app deploy/backup.sh
docker compose -f compose.prod.yaml exec -T app deploy/restore-test.sh
```

**Do this before you put real data in.** A backup pipeline is a hypothesis until it has
actually been restored once (design.md, "Restore drill") — the restore drill runs `manage.py
migrate` against the restored copy and compares every table's row count against the live
source, failing loudly on any mismatch. See "Backups" and "Restore drill" below for scheduling
this on an ongoing basis, and "Restoring from a backup" for what to do with a real backup
during an actual incident.

## Deploying without Docker (systemd)

The Docker Compose path (`README.md`) is recommended, but nothing about this app requires
Docker. This walks through the same startup logic — `docker-entrypoint.sh`, unmodified — run
directly under systemd instead of a container.

### Prerequisites

- A Linux host with systemd (any recent Debian/Ubuntu/Fedora VPS).
- `uv` installed for the service account that will run the app (see
  [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)).
- The `caddy` binary, either from your distro's package (which ships its own systemd unit —
  prefer it) or downloaded from [caddyserver.com](https://caddyserver.com/docs/install) if
  your distro doesn't package it. `deploy/systemd/plantoplate-caddy.service` is provided for
  the latter case.
- A system clock kept in sync (`timedatectl` should say `System clock synchronized: yes`) —
  see `README.md`'s prerequisite 3; the same stale/future-clock failure modes apply outside
  Docker too.

### Install

```bash
# 1. Service accounts — dedicated, unprivileged, no login shell.
sudo useradd --system --create-home --home-dir /opt/plantoplate --shell /usr/sbin/nologin plantoplate
sudo useradd --system --no-create-home --shell /usr/sbin/nologin caddy   # skip if using the distro's caddy package

# 2. Fetch the app.
sudo -u plantoplate git clone <this repository> /opt/plantoplate
cd /opt/plantoplate

# 3. Build the venv from the committed lockfile — exactly what the Docker image does.
sudo -u plantoplate uv sync --frozen --no-dev --group prod
#   Add --group postgres too if you're pointing DATABASE_URL at Postgres (see README.md's
#   "Switching to Postgres" — the same driver/config split applies here).

# 4. Config. /etc/plantoplate/plantoplate.env holds the same values .env holds for the Docker
#    path — copy .env.example as your starting point, but note the different DATA_DIR default
#    below (systemd has no named volume to supply it).
sudo mkdir -p /etc/plantoplate
sudo cp .env.example /etc/plantoplate/plantoplate.env
make secret   # paste the printed key into plantoplate.env's SECRET_KEY=
sudo chown root:plantoplate /etc/plantoplate/plantoplate.env
sudo chmod 640 /etc/plantoplate/plantoplate.env

# 5. Persistent data directory — the systemd-path equivalent of the Docker named volume.
sudo mkdir -p /var/lib/plantoplate
sudo chown plantoplate:plantoplate /var/lib/plantoplate

# 6. Static files directory (collectstatic writes here on every start, like the container's
#    ephemeral layer) and the entrypoint's own executable bit.
sudo -u plantoplate mkdir -p /opt/plantoplate/staticfiles
sudo chmod +x /opt/plantoplate/docker-entrypoint.sh /opt/plantoplate/deploy/backup.sh /opt/plantoplate/deploy/restore-test.sh

# 7. Caddyfile — same file the Docker path uses, with one edit: there is no Docker network
#    giving the app container the DNS name "app" here, so point the proxy at localhost instead.
sudo sed 's/reverse_proxy app:8000/reverse_proxy 127.0.0.1:8000/' Caddyfile | sudo tee /opt/plantoplate/Caddyfile.systemd >/dev/null
#    Either edit deploy/systemd/plantoplate-caddy.service's --config path to point at
#    Caddyfile.systemd, or (if using your distro's caddy package) copy it to
#    /etc/caddy/Caddyfile instead.

# 8. Install and start the units.
sudo cp deploy/systemd/plantoplate.service /etc/systemd/system/
sudo cp deploy/systemd/plantoplate-caddy.service /etc/systemd/system/   # skip if using the distro's caddy package
sudo systemctl daemon-reload
sudo systemctl enable --now plantoplate.service
sudo systemctl enable --now plantoplate-caddy.service   # or: sudo systemctl reload caddy
```

### Verify

```bash
sudo systemctl status plantoplate.service        # active (running)
sudo journalctl -u plantoplate.service -n 50      # migrate -> collectstatic -> "Starting gunicorn."
curl -k https://localhost/healthz/                # {"status": "ok", "database": "ok"}
```

The bootstrapped admin's one-time temp password is in the same journal:

```bash
sudo journalctl -u plantoplate.service | grep -A2 "Temporary password"
```

Everything else in `README.md`'s "First deployment" section — TLS behaviour, the temp
password flow, `bootstrap_admin --force` for a locked-out admin, `changepassword` as a last
resort, `seed_catalog` availability — applies identically here; only the process supervisor
and the data-directory location differ from the Docker path.

### Updating

```bash
cd /opt/plantoplate
sudo -u plantoplate git pull
sudo -u plantoplate uv sync --frozen --no-dev --group prod
sudo systemctl restart plantoplate.service
```

`docker-entrypoint.sh` re-runs `migrate --noinput` and `collectstatic --noinput` on every
start (both idempotent), exactly as it does in the container — a restart is the whole update
procedure, the same as `docker compose up -d --build` is on the Docker path.

## Backups

`deploy/backup.sh` produces, in one run: a checksummed, gzipped snapshot of the live SQLite
database (via SQLite's own Online Backup API — never a raw file copy, which can capture a torn
state on a WAL database), rotated into hourly/daily/weekly retention tiers and pruned; and a
nightly-scale `manage.py dumpdata` JSON export (engine-independent insurance, and the Postgres
migration path). See the script's own docstring for the exact mechanism and every environment
variable it reads.

### Scheduling

**systemd** (recommended for the systemd deployment path above):

```bash
sudo cp deploy/backup.service deploy/backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now backup.timer
sudo systemctl list-timers backup.timer   # confirm the next scheduled run
```

**Docker Compose**: there is no long-running "cron" container in `compose.prod.yaml` — run it
on the host's own cron or systemd timer instead, invoking it *inside* the container so it sees
the same `DATA_DIR`/`DATABASE_URL` the app does:

```cron
0 * * * *  cd /path/to/plantoplate && deploy/docker-backup.sh
```

`deploy/docker-backup.sh` takes the backup inside the container and then syncs it off-box from
the host (see "Off-box copy"). Running `deploy/backup.sh` in the container directly still works
for a local-only backup.

### Retention

- Hourly backups kept 24 hours, daily kept 30 days, weekly kept a year (`HOURLY_RETENTION_MINUTES`
  / `DAILY_RETENTION_DAYS` / `WEEKLY_RETENTION_DAYS`, overridable).
- The nightly `dumpdata` export is kept 30 days (`DUMPDATA_RETENTION_DAYS`).
- Pruning runs as part of every backup — there is nothing separate to schedule for it.

### Off-box copy

**A backup on the same disk as the database it backs up is not a backup.** Set one of these in
`plantoplate.env` / `.env` and `backup.sh` syncs the whole backup directory there after every
run:

```bash
RCLONE_REMOTE=myremote:plantoplate-backups   # requires `rclone` on PATH and configured
# or
RSYNC_TARGET=user@otherhost:/backups/plantoplate/
```

Neither is required for the script to run — with neither set, it logs that off-box sync is
unconfigured and continues; the backup itself, retention pruning, and the dumpdata export all
still happen.

A target that is set but whose tool is missing is an error, not a skip: the script exits non-zero
and says nothing was copied off-box.

**Docker Compose: sync from the host.** The app image contains no `rsync`, `rclone` or `ssh`, so
setting these inside the container cannot work. Set them in the environment of
`deploy/docker-backup.sh` on the host instead, which uses the host's tools and SSH keys:

```bash
RSYNC_TARGET=user@otherhost:/backups/plantoplate/ deploy/docker-backup.sh
```

The script reads `RSYNC_TARGET` / `RCLONE_REMOTE` from its environment, or from `.env` in the
directory it runs from. It stages a copy in `./backups-offbox` (mode 0700, refuses to delete a
directory that holds anything other than backup tiers) and holds a lock so overlapping cron runs
cannot collide.

Verify the first run properly: the files must exist on the other machine and
`sha256sum -c <file>.sha256` must pass there. The sidecars hold bare filenames, so they verify
from any directory.

## Restore drill

**A backup that has never been restored is a hypothesis, not a backup.** `deploy/restore-test.sh`
restores the most recent backup into a fresh scratch directory, verifies its checksum and
integrity, runs `manage.py migrate` against it (the realistic disaster path is *restore, then
migrate*, in that order — never the reverse), and compares every table's row count against the
live source database.

```bash
make restore-test
```

Run this after every first deployment, before putting real data in, and periodically
thereafter — a backup pipeline that silently stopped producing restorable backups six months
ago is worse than no backup pipeline, because it *looks* like one.

`make restore-test` restores into a temporary directory that is deleted when the drill
finishes; it never writes back to the live database. Pass `KEEP_SCRATCH=1` (and optionally
`SCRATCH_DIR=/some/path`) as environment variables to the underlying script directly if you
want to keep the restored copy around afterward to poke at.

## WAL checkpoint maintenance

SQLite's WAL mode (`config/settings/base.py`'s `SQLITE_OPTIONS`, load-bearing for the
concurrency this app depends on) grows a write-ahead log file until something checkpoints it.
SQLite auto-checkpoints at a page-count threshold, but a long-running read transaction can hold
that off, and the automatic checkpoint does not truncate the WAL file back to zero bytes even
when it does run. `manage.py checkpoint_wal` runs `PRAGMA wal_checkpoint(TRUNCATE)` explicitly.

Schedule it periodically — a busy-but-not-fully-checkpointed result is expected under real
traffic (a concurrent writer briefly held a lock) and safe to retry, not a failure:

```bash
# systemd (add a small oneshot service + timer, following backup.service/backup.timer as a
# template) or cron, inside the container for the Docker path:
0 3 * * *  cd /path/to/plantoplate && docker compose -f compose.prod.yaml exec -T app python manage.py checkpoint_wal
```

```bash
# systemd (non-Docker) path, run as the plantoplate user:
uv run manage.py checkpoint_wal
```

## Logging

`config/settings/prod.py` writes two rotating files under `LOG_DIR` (default `/app/data/logs`
under Docker Compose — the persistent data volume, so history survives a container recreate;
override with the `LOG_DIR` env var for either deployment path):

- `app.log` — everything at `INFO` and above, the day-to-day request/response trail.
- `error.log` — `ERROR` and above only, so chasing an incident does not mean grepping a week
  of routine traffic first.

Both are capped at 10 MB x 5 backups (50 MB) each and also mirrored to stderr (`docker compose
logs app` / `journalctl -u plantoplate.service`). Neither file, nor the console handler, ever
receives a password, session key, or raw request body — nothing in this project's own code
logs one, and Django's own request-logging path never includes local variable values in a
plain (non-HTML) traceback. Regression-guarded by
`core/tests/test_ops.py::test_logging_excludes_passwords`.

**Optional Sentry error reporting.** Off by default — a home server with no error-reporting
service is fine. To enable it: `uv add --group prod sentry-sdk` (a real dependency change,
needs the usual `uv` workflow — this is not installed by default), rebuild the image, then set
`SENTRY_DSN` in `.env` to your project's DSN. Setting `SENTRY_DSN` with `sentry-sdk` not
installed fails loudly at startup (`ImproperlyConfigured`) rather than silently running with
no error reporting.

## Updating a running deployment

**Docker Compose:**

```bash
git pull
make docker-build-prod
docker compose -f compose.prod.yaml up -d
```

`docker-entrypoint.sh` re-applies `migrate` and `collectstatic` on every start (both
idempotent) before `exec gunicorn` — that final `exec` is what makes the old container's
gunicorn receive a clean `SIGTERM` when Compose replaces it, rather than a force-kill mid
write. Neither `seed_catalog` nor `bootstrap_admin` re-runs; both are guarded by their own
first-run marker in the data volume (D18). Confirm the update actually took with the admin
dashboard's build-provenance panel (`GIT_SHA` / `BUILD_DATE`, D57) — if it still shows the old
commit, the build step above did not actually rebuild the image `up -d` picked up.

**systemd:** see "Updating" under "Deploying without Docker (systemd)" above — a `git pull` +
`uv sync --frozen` + `systemctl restart` accomplishes the same thing.

## Rolling back to a previous image

This project does not push images to a registry or tag them by version — `make
docker-build-prod` always builds from whatever commit is currently checked out. Rolling back
means checking out the previous commit and rebuilding from it, the same way forward:

```bash
git log --oneline -10          # find the commit you want to roll back to
git checkout <previous-sha>
make docker-build-prod
docker compose -f compose.prod.yaml up -d
```

Confirm the rollback actually took the same way you'd confirm an update: the admin
dashboard's `GIT_SHA` should read `<previous-sha>`.

**Database migrations do not roll back with the code.** If the commit you are rolling back
*past* applied a forward migration, the schema stays on the newer shape — Django does not
auto-reverse migrations on a code rollback, and this project ships no tooling that does either.
An application-level rollback (bad code, no schema change since the last good commit) is safe
with the steps above alone. A rollback that needs to undo a schema change as well means
restoring the database from a backup taken *before* that migration ran (see "Restoring from a
backup" below) in addition to rolling back the code — check `git log -- '*/migrations/'`
between the two commits to know whether this applies before you roll back.

## Rotating `SECRET_KEY`

**Rotating `SECRET_KEY` logs every user out, with no exception.** `SECRET_KEY` signs every
session cookie; changing it makes every existing cookie fail Django's signature check, which
is indistinguishable from "not logged in" (design.md's "Edge cases"). This is the intended
behaviour of a rotation, not a bug to route around — do it when you have a real reason
(suspected compromise, a scheduled rotation policy) and expect the support question "why did I
get logged out."

```bash
make secret                       # generate a fresh key
# edit .env's SECRET_KEY= to the new value
docker compose -f compose.prod.yaml up -d    # or: systemctl restart plantoplate.service
```

There is no partial or gradual rotation — the old key stops validating existing sessions the
moment the new one loads, on the next restart. Keep the old key noted somewhere safe until
you're confident the rotation went cleanly (there is no way to "undo" a rotation other than
setting `SECRET_KEY` back to the old value, which un-invalidates the old sessions again).

## Restoring from a backup (disaster recovery)

This is the real-incident procedure — not the read-only drill (`make restore-test` /
`deploy/restore-test.sh`, "Restore drill" above), which never touches the live database.
This one does: **stop the app first**, so nothing writes to the database while you replace it.

```bash
# 1. Stop the app -- Caddy alone can stay up to serve a maintenance response, if you want one.
docker compose -f compose.prod.yaml stop app

# 2. Pick the backup to restore -- newest, or a specific one.
docker compose -f compose.prod.yaml run --rm app \
    bash -c 'ls -la /app/data/backups/hourly /app/data/backups/daily /app/data/backups/weekly'

# 3. Verify its checksum, then replace the live database with it. Never skip the checksum
#    check -- a corrupted backup file restored without verifying it is a second outage on top
#    of the first.
docker compose -f compose.prod.yaml run --rm app bash -c '
    set -euo pipefail
    cd /app/data/backups/hourly
    FILE=plantoplate-<timestamp>.sqlite3.gz    # the one you picked in step 2
    sha256sum -c "$FILE.sha256"
    gunzip -c "$FILE" > /app/data/db.sqlite3.restored
    mv /app/data/db.sqlite3 /app/data/db.sqlite3.pre-restore.bak
    mv /app/data/db.sqlite3.restored /app/data/db.sqlite3
'

# 4. Restore, then migrate -- that order, never the reverse (design.md's edge case: a backup
#    can be older than the schema currently on disk).
docker compose -f compose.prod.yaml run --rm app python manage.py migrate --noinput

# 5. Bring the app back up and verify.
docker compose -f compose.prod.yaml up -d app
curl -k https://<your-host>/healthz/
```

Keep `db.sqlite3.pre-restore.bak` until you've confirmed the restored data is actually what
you wanted — it is your undo button for this exact procedure. Delete it by hand once you're
sure (it lives on the same data volume as the live database, so it counts against disk space
but not against anything this project automates).

**If instead you need the engine-independent JSON export** (a SQLite version problem, or the
Postgres migration path below), `loaddata` it into a freshly migrated, empty database rather
than over a populated one — see "Migrating to Postgres" for the exact sequence; the exclusions
`backup.sh` applies to the dumpdata export (`contenttypes`, `auth.permission`, `sessions`)
exist specifically so this loads cleanly into a database whose own `migrate` already populated
those tables itself.

## Migrating to Postgres

The app's code runs unchanged against Postgres (no SQLite-specific SQL anywhere), but this is
a real cutover with downtime, not a config toggle you flip on a live database — plan a
maintenance window. See README.md's "Switching to Postgres" for the full mechanics
(`INCLUDE_POSTGRES`, the `postgres` dependency group, `compose.yaml`'s commented-out service);
this section is the operational sequence around it:

1. **Back up first.** Run `deploy/backup.sh` (or `make backup` locally) and confirm the
   dumpdata export succeeded — this is your rollback path if the cutover goes wrong, and the
   only one that survives a *database engine* change.
2. Stop the app: `docker compose -f compose.prod.yaml stop app`.
3. Configure and start Postgres per README.md's steps 1–2 (`.env`'s `DATABASE_URL` /
   `POSTGRES_*` / `INCLUDE_POSTGRES=true`, uncomment the `postgres` service).
4. Rebuild with the driver included and bring up an *empty* Postgres-backed app so it can
   migrate its own schema: `make docker-build-prod && docker compose -f compose.prod.yaml up
   -d postgres app` — the entrypoint's `migrate` step creates every table fresh.
5. Load the data: `docker compose -f compose.prod.yaml exec -T app python manage.py loaddata
   <the dumpdata export from step 1>`. Use `gunzip -c <file>.json.gz | docker compose -f
   compose.prod.yaml exec -T app python manage.py loaddata --format=json -` if loading
   directly from the compressed export rather than extracting it first.
6. Verify: `/healthz/`, log in, spot-check that recent recipes/dishes are present, then run
   `deploy/restore-test.sh`-style row-count sanity by hand (the script itself is SQLite-only —
   it shells out to `sqlite3`/the stdlib `sqlite3` module — so it does not run against
   Postgres directly; compare counts via `manage.py shell` instead).

## Moving to a VPS

Nothing in this app assumes a home LAN — `ALLOWED_HOSTS`, `DATABASE_URL`, and `MEDIA_ROOT` are
all environment-driven, and Caddy provisions a real Let's Encrypt certificate automatically
the moment `SITE_ADDRESS` names a publicly resolvable domain instead of `localhost` (see
"TLS" in README.md). Moving is the same first-deployment sequence at the top of this document,
run against the new box, plus:

- Point DNS (or your Tailscale MagicDNS name) at the new box's address before starting Caddy,
  so the ACME HTTP-01 challenge (or Tailscale's own cert issuance) can actually complete.
- If you're moving *data*, not starting fresh: restore the most recent backup onto the new box
  before first boot (copy the backup file over, then follow "Restoring from a backup" above
  once the stack is up), rather than trying to migrate the running containers themselves.
- Prefer the systemd path ("Deploying without Docker" above) on a minimal VPS image that
  doesn't already have Docker, rather than adding Docker just for this app.
- The synchronised-clock prerequisite (README.md's prerequisite 3) applies to a fresh VPS
  image too — cloud images are usually fine, but a from-scratch install or a VM with paused
  time is not a safe assumption.

## Diagnosing `database is locked`

SQLite serialises writes; this app's `SQLITE_OPTIONS` (`config/settings/base.py`) already sets
`journal_mode=WAL`, `busy_timeout=5000`, and `transaction_mode=IMMEDIATE` specifically so a
second writer *waits* up to 5 seconds for the first one to finish rather than erroring
immediately — most transient contention resolves invisibly within that window. Seeing
`database is locked` in the logs at all past that means something is holding a write lock
longer than expected. In rough order of likelihood:

1. **Gunicorn is running more workers/processes than `gunicorn.conf.py` specifies.** This app
   depends on *threads, not processes* — many SQLite connections from separate OS processes
   contending for one write lock is the classic way to get this error under real load. Confirm
   `gunicorn.conf.py`'s `workers = 2` hasn't been overridden on the command line or by an env
   var, and that nothing else (a stray second `gunicorn` invocation, a debug shell holding a
   connection open) is writing to the same database file concurrently.
2. **A long-running read transaction is holding back WAL checkpointing**, letting the
   write-ahead log grow — not the same error, but the same underlying pressure. Run `manage.py
   checkpoint_wal` (see "WAL checkpoint maintenance" above) and schedule it periodically if you
   haven't already.
3. **The database file lives on a network filesystem** (NFS, some cloud-mounted volumes)
   whose locking semantics do not match local disk. SQLite's locking assumes a local
   filesystem; this app's Docker named volumes and systemd `DATA_DIR` are both meant to be
   local disk. If the underlying storage is remote, that's the fix, not a SQLite setting.
4. **A management command or shell session left a transaction open.** `manage.py shell`
   sessions and ad-hoc scripts that open a connection and never close it (or wrap work in
   `atomic()` and never exit the block, e.g. a crashed script) hold a lock for as long as the
   process lives. Check for stray Python processes against this database.

If none of the above explains it and it's still happening under normal traffic, it's worth
filing as a real bug against this app's transaction scope (design.md is explicit: "keep write
transactions short — never across an HTTP call or slow loop") rather than working around it —
grep for anywhere a view or service holds a transaction open across something slow (a network
call, a large loop) and shorten it.

## Deployment rehearsal (10.17) — results

test-plan.md's 14 manual verifications, performed 2026-09-17. This implementation sandbox has
no Docker daemon and no browser — the same environment limit already disclosed for 10.7's live
Caddy check and 10.13's `make`-unavailable restore drill. Each result below says exactly what
was and wasn't actually exercised; nothing here is claimed without having been run.

**Deployment (checks 1–6) — could not be exercised in this sandbox.** Bringing up
`compose.prod.yaml`, confirming TLS/`DEBUG`/static-serving/restart-survival in a real
container, and browsing the live app with devtools open all require Docker and a browser,
neither available here. These need to be run for real on a machine with Docker before this
deployment is trusted in production — the systemd/Docker Compose paths above have been
reviewed line by line and unit-tested (`config/tests/test_caddyfile.py`,
`config/tests/test_gunicorn_conf.py`, `config/tests/test_security_settings.py`), but that is
not a substitute for actually watching a real container come up.

One check under this heading *was* exercised, because it does not require Docker or TLS —
check 5's CSP sweep, specifically the part flagged as never having been verified: **Django
admin pages using `autocomplete_fields` (select2)**. Method, since no browser was available
either: rendered `IngredientAdmin`, `RecipeAdmin`, `DishAdmin`, and `MealPlanProfileAdmin`'s
add forms (the four admin classes that declare `autocomplete_fields`) through Django's real
request/response cycle as an authenticated superuser, then inspected the actual HTML and
headers returned:

- `Content-Security-Policy` header present on every page, identical to the policy already
  pinned by `config/tests/test_csp.py` (no `unsafe-inline` anywhere).
- Zero inline `style="..."` attributes, zero inline `on*=` event handler attributes, in any of
  the four rendered pages.
- Every `<script>` tag is either a same-origin `src=` reference or a `type="application/json"`
  data island (Django's own CSP-safe pattern for passing server data to an external script,
  e.g. `admin/js/change_form.js`) — never an inline executable script body.
- The vendored select2 JS/CSS Django's admin ships (`django/contrib/admin/static/admin/{js,css}
  /vendor/select2/`) contains no `setAttribute("style", ...)`, no dynamically injected `<style>`
  element, no `eval`/`document.write`, and no external (`http(s)://`) or `data:` URI
  references outside what `img-src 'self' data:` already permits.

**Result: PASS**, with one honest gap — this confirms the *markup and headers* carry nothing a
CSP would block, via the real Django rendering pipeline, but does not confirm it via an actual
browser's CSP enforcement + devtools console (select2's JS was inspected statically, not
executed in a real DOM). Re-run this check with a real browser against a real deployment
before fully retiring the "never verified for admin pages" finding — recorded here rather than
closed silently.

**Backups (checks 7–10) — exercised against a scratch copy, not the live dev database**, per
CLAUDE.md's rule that backup/restore scripts get tested against scratch copies rather than the
real `db.sqlite3` without standing permission for that specific script:

*Note added 2026-09-17 (dev-test-walkthrough):* the caution above was this implementation
session's own choice, not a hard requirement — `deploy/backup.sh` only ever *reads* the source
database (see its header comment), and `deploy/restore-test.sh` restores into its own scratch
directory regardless of what it's pointed at, so neither script actually mutates a live
`db.sqlite3`. `Plan/10-Security-And-Deployment/dev-test-walkthrough.md` Scenario A6 runs both
directly against the real dev-test dataset on that basis — a genuine, and different, production
restore (overwriting the running database) is the operation that still needs a scratch copy or
standing permission first.

- **Check 7 (backup produces a checksummed, integrity-checked file):** PASS. `deploy/backup.sh`
  run against a scratch copy of this checkout's `db.sqlite3` (39 recipes / 25 dishes / 176
  ingredients — the same dev-test dataset 10.13 used) produced hourly/daily/weekly
  `.sqlite3.gz` files and a `dumpdata` JSON export, all with `.sha256` sidecars; `sha256sum -c`
  verified clean against all four.
- **Check 8 (a real restore, opened, recipes present):** PASS. `deploy/restore-test.sh` against
  the same scratch backup restored cleanly, applied 5 pending migrations (the scratch
  database's schema was slightly behind current `HEAD` — see "Noticed but not covered" below),
  and matched **every one of 39 application tables** row-for-row against the source
  (`RESULT PASS`, full output preserved in this session's transcript). "Opened the app against
  it" specifically (rather than a row-count comparison) was not additionally done — 10.13's own
  restore drill already establishes the data round-trips through Django's ORM correctly via the
  `migrate` step succeeding and the app's own tables matching; a full `runserver` against the
  restored copy was judged redundant given no Docker/browser were available for check 1–6
  anyway.
- **Check 9 (retention pruning leaves the expected set):** PASS by test coverage
  (`deploy/tests/test_backup.py::test_retention_prunes_correctly`, fixture-driven against dated
  files spanning each tier's boundary) rather than a fresh manual run this session — the
  scratch run above only ran once, too recent for any tier's retention window to prune anything
  by design.
- **Check 10 (off-box copy actually lands off-box):** *superseded by the live rehearsal at the
  end of this file.* Original note: **not verified live** — this sandbox has
  no real `rclone` remote or SSH-reachable `rsync` target configured, and standing one up
  purely to exercise this check was judged out of scope. `deploy/backup.sh`'s off-box step is
  unit-tested with a stubbed command (`deploy/tests/test_backup.py`) confirming it invokes
  `rclone sync` / `rsync` correctly when configured, and logs a clear skip message when
  neither `RCLONE_REMOTE` nor `RSYNC_TARGET` is set — but "the file actually lands on a
  different disk" needs a real remote to confirm, which is a genuine follow-up for whoever
  configures a real off-box destination before trusting this in production.

**Security spot checks (checks 11–14) — exercised live**, via Django's real request/response
cycle (test client) against the actual view/permission/serializer stack, not merely unit-test
assertions already in the suite:

- **Check 11 (regular user hits `/admin/` — denied):** PASS. A newly created, non-staff user,
  authenticated, requesting `/admin/` got a `302` redirect away from the admin (Django's
  `has_permission` check failing for a non-staff account), never the admin index.
- **Check 12 (fetch another user's private recipe by ID — 404, not 403):** PASS, both surfaces.
  A private `Recipe` owned by one user, fetched by a second, unrelated authenticated user, via
  both the HTML detail view (`/recipes/<id>/`) and the API (`/api/recipes/<id>/`), returned
  `404` in both cases — never `403`, confirming the object simply doesn't exist from the
  requester's point of view (IDOR posture, `Plan/ARCHITECTURE.md` security posture #1).
- **Check 13 (exceed the login throttle — 429):** PASS. Five wrong-password POSTs followed by a
  sixth from the same client returned `429` on the sixth, live through the real
  `TempPasswordAwareLoginView` + `ThrottledLoginMixin` path (the same one this task's blocking
  rework fixed — see this task's `.review-findings.md`, now resolved and removed).
- **Check 14 (session cookie is `Secure`, `HttpOnly`, `SameSite=Lax`):** PASS. With the
  production cookie settings applied (`SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` /
  `SESSION_COOKIE_HTTPONLY` / `SESSION_COOKIE_SAMESITE` — the same values
  `config/settings/prod.py` and `config/settings/base.py` set), the session cookie returned to
  an authenticated client carried `secure=True`, `httponly=True`, `samesite='Lax'`. Real TLS
  termination itself (the browser actually refusing to send a `Secure` cookie over plain HTTP)
  could not be exercised without Docker/Caddy — the cookie *attributes* Django emits were
  confirmed directly instead.

**Noticed but not covered by any plan file:** the scratch-copied dev-test `db.sqlite3` used for
the backup/restore checks above was five migrations behind this branch's current `HEAD`
(`catalog.0003`, `lists.0002`, `meals.0003`, `planner.0004`, `recipes.0005` — all
`max_length`/field-adjustment migrations from later in task 10's own input-validation sweep).
The restore drill's own `migrate` step applied them without incident, which is exactly the
"restore, then migrate" edge case design.md calls out working as intended — but it means the
actual on-disk dev database this repository ships alongside has not itself been migrated
forward in a while. Not a task 10 concern to fix (touching the real `db.sqlite3` needs
permission this session was not asked for), but worth a `uv run manage.py migrate` next time
someone is doing interactive dev-testing against it.

## Live rehearsal results (2026-11-01, Docker 29 on Fedora, SELinux enforcing)

A clean-volume `compose.prod.yaml` deployment, browsed over the tailnet, found problems no unit
test could. All are fixed in the repo.

- Caddy crash-looped with `permission denied` reading the Caddyfile (SELinux): `:ro,z`.
- Caddy's probe sent `Host: app:8000`, Django answered 400, Caddy would mark the app down:
  `health_headers`.
- Caddy's own healthcheck used `localhost` (resolves to `::1` on Alpine): `127.0.0.1`.
- `*.ts.net` TLS needs the Tailscale socket and tailnet HTTPS certificates:
  `compose.tailscale.yaml`.
- htmx injects an inline `<style>` that the CSP blocks, on every page: `htmx-config` meta tag.
- The image has no rsync/rclone/ssh and `backup.sh` reported "no target configured" even when
  one was set: it now fails loudly, and `deploy/docker-backup.sh` syncs from the host.
- Checksum sidecars held absolute container paths and could not be verified off-box: bare names.

Verified live: first boot healthy, `DEBUG` false, static through Caddy (WhiteNoise), security
headers, resource limits applied, a spoofed `X-Forwarded-For` ignored (six wrong logins from six
spoofed addresses were throttled as one client), backup and restore drill, off-box copy landing
with verifying checksums, survival of a Docker daemon restart. A gunicorn access log shows
Caddy's address, not the client's, so it cannot demonstrate header handling; test via the
throttle instead.
