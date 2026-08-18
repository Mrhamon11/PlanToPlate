# PlanToPlate

A self-hosted recipe, meal-planning and shopping-list app for a household of 10–20 users,
built with Django and DRF. See [`Plan/MILESTONES.md`](Plan/MILESTONES.md) for the full
architecture and decision log.

## First deployment (Docker Compose)

This is the whole setup. Nothing here needs a step that isn't written down.

**Prerequisites:** Docker and Docker Compose on the target machine (a home server, a Pi, a
VPS — anything that runs Docker).

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

On first boot the entrypoint applies migrations, collects static files, and (once the
management commands below exist) seeds the ingredient/unit catalog and creates an admin
account, printing its one-time temp password to the container logs:

```bash
docker compose logs app | grep -A2 "temp password"
```

Then open `https://localhost/` (or the domain you set in `SITE_ADDRESS` — see below) and log
in with that username and temp password. You'll be asked to set a real password on first
login.

Restarting the stack (`docker compose restart`, or `docker compose down && docker compose
up`) re-applies migrations and collects static files (both are safe to repeat) but never
re-seeds the catalog or creates a second admin. Each of the two first-run commands has its
**own** on-disk marker in the data volume (`.ran-seed_catalog`, `.ran-bootstrap_admin`),
written only after that command actually completes — so each one runs exactly once, and a
skip (see below) leaves no marker behind, letting the command run automatically the first
time it becomes available.

### Current status: `seed_catalog` and `bootstrap_admin` are not implemented yet

Those two management commands land in tasks 04 and 01 respectively. Until then the
entrypoint detects that they don't exist, logs a line saying so, and skips them cleanly —
it does not fail the deploy, and it does not write a marker for the skipped command. Once a
task ships its command and the image is rebuilt, the very next boot picks it up
automatically, with no volume cleanup needed.

That means right now, on a clean machine, first boot brings up a working app and an empty
database with **no admin account**. To reach a working `/admin/` login today:

```bash
docker compose exec app python manage.py createsuperuser
```

This step goes away once task 01 ships `bootstrap_admin` — the walkthrough above becomes
accurate as written, with no manual command needed.

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
