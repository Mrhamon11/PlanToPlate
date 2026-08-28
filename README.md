# PlanToPlate

A self-hosted recipe, meal-planning and shopping-list app for a household of 10–20 users,
built with Django and DRF. See [`Plan/ARCHITECTURE.md`](Plan/ARCHITECTURE.md) for the
architecture and decision log, and [`Plan/MILESTONES.md`](Plan/MILESTONES.md) for task status.

## First deployment (Docker Compose)

This is the whole setup. Nothing here needs a step that isn't written down.

**Prerequisites**

1. **Docker and Docker Compose** on the target machine (a home server, a Pi, a VPS — anything
   that runs Docker).
2. **Your user must be able to reach the Docker daemon.** If `docker ps` fails with
   `permission denied ... /var/run/docker.sock`, add yourself to the `docker` group:

   ```bash
   sudo usermod -aG docker $USER
   newgrp docker        # applies the group to *this* shell without logging out
   ```

   `usermod` alone does not affect shells that are already open — either run `newgrp docker`
   in each one, or log out and back in for it to apply everywhere.
3. **The system clock must be synchronised.** The image build installs Debian packages, and
   apt rejects repository metadata that is timestamped in the future relative to the build
   host. A clock running behind real time therefore fails the build with
   `Release file ... is not valid yet`. Check and fix before building:

   ```bash
   timedatectl                      # want: System clock synchronized: yes
   sudo chronyc makestep            # force an immediate sync if it says no
   ```

   The mirror-image symptom, `Release file ... is expired`, means the clock is running ahead.
   Both are host clock problems, not repository problems.

```bash
git clone <this repository> plantoplate
cd plantoplate
cp .env.example .env
make secret          # prints a fresh SECRET_KEY — paste it into .env's SECRET_KEY=
docker compose up
```

`SECRET_KEY` is the one value with no default: a defaulted secret key means forgeable
sessions, so the app refuses to start without one. Everything else in `.env.example` already
has a sensible default for a first run.

On first boot the entrypoint applies migrations, collects static files, creates an admin
account (`bootstrap_admin`, printing its one-time temp password to the container logs), and —
once `seed_catalog` (task 04) exists — seeds the ingredient/unit catalog:

```bash
docker compose logs app | grep -A2 "Temporary password"
```

That password is not stored anywhere else and this is the only way to read it back — it stays
in the container log (readable this way) until that log is rotated or cleared, so treat it as
sensitive and complete the forced password change on first login promptly.

Then open `https://localhost/` (or the domain you set in `SITE_ADDRESS` — see below) and log
in with username `admin` and that temp password. You'll be asked to set a real password on
first login.

Restarting the stack (`docker compose restart`, or `docker compose down && docker compose
up`) re-applies migrations and collects static files (both are safe to repeat) but never
re-seeds the catalog or creates a second admin. Each of the two first-run commands has its
**own** on-disk marker in the data volume (`.ran-seed_catalog`, `.ran-bootstrap_admin`),
written only after that command actually completes — so each one runs exactly once, and a
skip (see below) leaves no marker behind, letting the command run automatically the first
time it becomes available.

### Current status: `seed_catalog` is not implemented yet

That management command lands in task 04. Until then the entrypoint detects that it doesn't
exist, logs a line saying so, and skips it cleanly — it does not fail the deploy, and it does
not write a marker for the skipped command. Once task 04 ships the command and the image is
rebuilt, the very next boot picks it up automatically, with no volume cleanup needed.

That means right now, on a clean machine, first boot brings up a working app with an admin
account (`bootstrap_admin`, task 01) but an empty ingredient/unit catalog.

If the admin account is ever locked out — the temp password's 7-day expiry passed with no
login, for instance — there is no self-service recovery; reset it directly:

```bash
docker compose exec app python manage.py changepassword admin
```

`changepassword` cannot help if the account was *deactivated* (a deactivated admin cannot log
in whatever its password is) and does not exist at all if the admin was created under another
name. For those, re-run the bootstrap command with `--force`: it reactivates the account
holding `--username`, re-grants staff/superuser, and prints a fresh one-time temp password,
exactly as on first boot.

```bash
docker compose exec app python manage.py bootstrap_admin --force
```

Without `--force` the command refuses whenever a usable admin already exists, or the requested
username is taken — so it stays safe to run by hand, and the entrypoint's `.ran-bootstrap_admin`
marker means a restart never re-runs it on its own.

### TLS

Caddy provisions TLS automatically. `SITE_ADDRESS` in `.env` controls how:

- Left unset (default: `localhost`) — Caddy issues a certificate from its own internal CA.
  Browsers and `curl` will warn it's untrusted (`curl -k` to bypass); this is expected and
  fine for a home LAN reached over Tailscale.
- Set to a real, publicly resolvable domain — Caddy requests a publicly trusted certificate
  from Let's Encrypt automatically. Make sure `ALLOWED_HOSTS` in `.env` includes that domain,
  and that ports 80/443 are reachable from the internet for the ACME challenge. You do not
  need to add `127.0.0.1` yourself — `config/settings/prod.py` always appends it for the
  Compose healthcheck, which hits gunicorn directly and cannot use the public hostname (see
  `.env.example`).

### Data persistence

The SQLite database and uploaded media live in named Docker volumes
(`plantoplate_data`, `plantoplate_media`), not the container's writable layer, so they survive
`docker compose restart`, `docker compose down && docker compose up`, and image rebuilds.
Only `docker compose down -v` (which explicitly removes volumes) or deleting the volumes by
hand loses data.

### Switching to Postgres

The app's code runs unchanged against Postgres — no SQLite-specific SQL anywhere, and the
pragma/`transaction_mode` block in `config/settings/base.py` is conditional on the database
engine specifically so this swap stays a configuration change, not a code change. The
driver, however, is **not** installed by default: `psycopg[binary]` lives in the optional
`postgres` dependency group in `pyproject.toml` rather than the main dependency list, so a
default SQLite-only deployment — what this project is sized for — never installs a database
driver it doesn't need. Switching to Postgres means both configuring it and rebuilding the
image with that group included:

1. In `.env`, set `DATABASE_URL=postgres://plantoplate:<password>@postgres:5432/plantoplate`,
   the matching `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`, and
   `INCLUDE_POSTGRES=true`. That last variable is a Docker build arg (wired up in
   `compose.yaml`'s `app.build.args`) that tells the image build to also install the
   `postgres` dependency group from `uv.lock` — the app can't reach Postgres without it, and
   leaving it unset (the default) keeps the driver out of the image entirely.
2. Uncomment the `postgres` service (and its volume) in `compose.yaml`.
3. `docker compose up --build` — the `--build` matters here, since `INCLUDE_POSTGRES` only
   takes effect on a rebuild, not a plain restart of the existing SQLite-only image.

Outside Docker (local `uv run` development against a Postgres instance), install the driver
with `uv sync --group postgres` before running `migrate` — `uv run --with psycopg[binary]`
proves the settings are portable but does not install anything into `uv.lock`, so it's not a
substitute for the real group when you actually intend to run against Postgres.

### Stopping the stack

`docker compose stop` shuts gunicorn down gracefully (it receives `SIGTERM` directly, because
the entrypoint's final step is `exec gunicorn`, making gunicorn PID 1 in the container) —
important on SQLite, where a force-kill mid-write is how a database gets corrupted.

### Health check

`GET /healthz/` returns `{"status": "ok", "database": "ok"}` backed by a real database
round-trip. Docker Compose uses it to decide whether the `app` service is actually healthy,
not merely running; Caddy only starts routing to it once that check passes.

### Verifying a deployment

After `docker compose up`, these four checks confirm the stack is genuinely working rather
than merely running:

```bash
docker compose ps                      # app should read "healthy", not just "up"
curl -k https://localhost/healthz/     # {"status": "ok", "database": "ok"}
docker compose logs app | tail -20     # migrate -> collectstatic -> "Starting gunicorn."
```

Then confirm the data actually persists, which is the failure that matters most on a
self-hosted box:

```bash
docker compose down && docker compose up -d
docker compose logs app | grep -i "first-run\|already recorded"
```

The database survives, and each first-run command reports either that it is skipped (not
implemented yet) or already recorded done. It must never re-seed.

### If the stack does not come up

- **`app` never becomes `healthy`, and Caddy never starts.** Almost always `ALLOWED_HOSTS`.
  The healthcheck reaches gunicorn on `127.0.0.1`, so Django rejects the request with 400 if
  that host is not allowed — and because Caddy waits on `service_healthy`, nothing gets
  served at all. `prod.py` appends `127.0.0.1` for you, so this should not happen; if it
  does, check `docker compose logs app` for `Invalid HTTP_HOST header`.
- **Build fails with `Release file ... is not valid yet`.** Host clock, not the build. See
  prerequisite 3 above.
- **`permission denied` on the Docker socket.** See prerequisite 2 above.
- **App exits immediately on boot.** Check `SECRET_KEY` is actually set in `.env` — it has no
  default and the app refuses to start without one.

## Local development

Local development runs outside Docker, in a `uv`-managed virtual environment.

```bash
uv sync                        # install dependencies into .venv
cp .env.example .env
make secret                    # paste the printed key into .env
uv run manage.py migrate
uv run manage.py runserver
```

Common tasks (see `Makefile` for the full list):

```bash
make test    # uv run pytest
make lint    # uv run ruff check .
make fmt     # uv run ruff format .
make check   # uv run manage.py check
make migrate # uv run manage.py migrate
make shell   # uv run manage.py shell
```

Never `pip install` anything directly — dependencies are managed with `uv add` / `uv remove`
so `uv.lock` (and therefore the Docker image, which installs from the same lockfile) stays in
sync with what's actually used.
