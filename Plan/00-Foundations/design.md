# 00 — Foundations · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

A Django project that boots, has a test suite that runs, a linter that passes, and a
deployment story — before any domain code exists. Nothing here is user-visible. Everything
here is something that is painful to retrofit.

**Depends on:** nothing. This is the first task.
**Enables:** every other task.

## What gets built

### Dependency management — `uv`

`pyproject.toml` + `uv.lock`, both committed. Dependency groups: default, `dev`, `prod`.

```
django>=5.1,<6      djangorestframework      django-environ
django-filter       drf-spectacular          whitenoise
[dev]  pytest  pytest-django  pytest-cov  factory-boy  ruff  django-debug-toolbar
[prod] gunicorn
```

Django 5.1 is the floor because `OPTIONS["transaction_mode"]` for SQLite arrived there, and
the concurrency configuration depends on it.

### Settings split

`config/settings/` with `base.py`, `dev.py`, `prod.py`, `test.py`; `DJANGO_SETTINGS_MODULE`
selects. **No secrets in any settings file** — everything sensitive comes from the environment
via `django-environ`, with `.env.example` committed and `.env` gitignored.

`base.py` must contain, at minimum:

```python
env = environ.Env(DEBUG=(bool, False))
SECRET_KEY = env("SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR}/db.sqlite3")}

if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"]["OPTIONS"] = {
        "init_command": (
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; "
            "PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;"
        ),
        "transaction_mode": "IMMEDIATE",
    }
```

The pragma block is conditional on the engine so that pointing `DATABASE_URL` at Postgres does
not explode. That conditional *is* the portability promise from `MILESTONES.md` §2 — it is the
one line that keeps the escape hatch real rather than aspirational.

`prod.py` adds `DEBUG=False`, `ALLOWED_HOSTS` from env, `SECURE_SSL_REDIRECT`,
`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS, `SECURE_PROXY_SSL_HEADER` (we sit behind
Caddy), and whitenoise storage.

`test.py` uses an in-memory SQLite database and the fast MD5 password hasher.

### App skeletons

Create empty-but-registered apps now, so later tasks only add files and never restructure:
`core`, `accounts`, `catalog`, `recipes`, `meals`, `lists`, `planner`.

Each gets an `apps.py` with an explicit `label` and an empty `tests/` package.

### Tooling

- **ruff** — configured in `pyproject.toml`, line length 100, rule set `E,F,I,N,UP,B,DJ,S`.
  `S` (bandit) earns its place on a project with a stated security requirement.
- **pytest** — `DJANGO_SETTINGS_MODULE=config.settings.test`, `--strict-markers`, coverage on.
- **Root `conftest.py`** providing the fixtures every later task will want: `api_client`,
  `user_factory`, `authenticated_client`. Writing them once here prevents seven apps from
  inventing seven slightly different user factories.
- **Makefile** wrapping the commands in `CLAUDE.md` §8.

### Development environment

**All development happens inside a virtual environment, always.** `uv` creates and manages
`.venv` automatically — you never create or activate it by hand. Every command runs through
`uv run`, which resolves the venv itself:

```bash
uv sync                     # create/update .venv from uv.lock
uv run manage.py runserver  # runs inside .venv, no activation needed
uv run pytest
```

**Never `pip install` anything.** A package installed outside `uv` is absent from `uv.lock`,
which means it is absent from the container, which means the code works on the dev machine and
fails in production. Dependencies change only via `uv add` / `uv remove`, which update the
lockfile.

The venv and the container image are the **same dependency set**, because `uv.lock` drives
both. That is what keeps dev and prod from drifting, and it is the reason the lockfile is
committed.

### Docker and local run

The deployment target is Docker Compose on a local server, and the goal is that deploying is
`docker compose up` with no manual setup steps afterward. That requires more than a Dockerfile.

**`Dockerfile`** — multi-stage, non-root:

- Builder stage: `uv sync --frozen --no-dev` against the committed `uv.lock`. `--frozen`
  means the build **fails** rather than silently resolving different versions — a build that
  quietly upgrades a dependency is not reproducible.
- Runtime stage: copy the built `.venv` and the app, drop to a non-root user.
- **System packages** the Python wheels need: `libjpeg`, `zlib`, and `libwebp` for Pillow
  (task N1), plus `libheif` if HEIC support is wanted. Pure-Python wheels cover most of this,
  but Pillow is the usual exception. Install them in the runtime stage, not just the builder,
  or the image builds and then fails at first image upload.
- Pin the base image by digest, not just tag, so a rebuild six months from now produces the
  same image.

**`.dockerignore`** must exclude `.venv`, `db.sqlite3`, `*.sqlite3-wal`, `*.sqlite3-shm`,
`.env`, `media/`, `.git`, and `__pycache__`. Two of these matter more than they look:

- Copying a host `.venv` into the image produces a broken image — the paths and the
  interpreter are wrong for the container.
- Copying a local `db.sqlite3` or `.env` **bakes your data and your secrets into the image
  layers**, where they survive even if a later layer deletes them.

**`docker-entrypoint.sh`** — this is what makes the container work out of the box. On every
start, before handing off to gunicorn:

1. Wait for the database to be reachable (a no-op for SQLite; matters if you switch to Postgres).
2. `manage.py migrate --noinput` — idempotent, so it is safe on every boot.
3. `manage.py collectstatic --noinput` — likewise.
4. On first run only (detected by a marker in the data volume): `seed_catalog` (task 04) and
   `bootstrap_admin` (task 01), printing the generated admin temp password to the container
   logs **once**.
5. `exec gunicorn …` so gunicorn becomes PID 1 and receives signals properly. Without `exec`,
   `docker compose stop` kills the shell and leaves gunicorn to be force-killed — which on
   SQLite risks stopping mid-write.

Steps 2 and 3 are idempotent by design; step 4 is guarded so a restart never re-seeds or
re-creates the admin.

**`compose.yaml`** — app plus Caddy, named volumes for the SQLite file and `MEDIA_ROOT` (a
container that loses the database on restart is worse than no container), `restart: unless-
stopped`, and a `healthcheck:` pointed at `/healthz/` so Compose knows whether the app is
actually up rather than merely running.

It must also work unchanged against Postgres by swapping `DATABASE_URL` and uncommenting a
`postgres` service. Verifying that swap is part of this task's test plan, not a claim left for
later.

**The one manual step, and why it stays manual.** `SECRET_KEY` has no default and startup
fails without it — deliberately, since a defaulted secret key means forgeable sessions. So
first deployment is: copy `.env.example` to `.env`, run `make secret` to generate a key, then
`docker compose up`. That is the whole setup. Auto-generating a key into the volume instead
was considered and rejected: it hides a security-critical value in a place people forget to
back up, and rotating it silently logs everyone out with no explanation.

**Build architecture.** If the local server is ARM (a Pi or similar) and you build on an x86
laptop, build with `docker buildx --platform linux/arm64` or the image will not run. Building
on the server itself avoids the issue entirely and is the simpler default at this scale.

### Health check

`GET /healthz/` returning `{"status": "ok", "database": "ok"}`, backed by a real `SELECT 1`.
Caddy and any future uptime monitor need it, and it is the fastest way to prove the whole
stack is wired end to end.

## Edge cases

- A missing `SECRET_KEY` must fail loudly at startup rather than falling back to a default.
  A defaulted secret key in production means forgeable sessions.
- WAL mode creates `-wal` and `-shm` sidecar files. `.gitignore` must cover them, and the
  backup script in task 10 must account for them.
- `uv.lock` is committed — reproducible builds are the entire point of a lockfile.

## Security notes

There is almost no user-facing surface yet, but the settings written here determine the
production posture of everything that follows. `manage.py check --deploy` is expected to be
noisy under dev settings and **clean under prod settings**; that gap is the deliverable.

## Open decisions for the implementer

None. If something here is ambiguous, ask rather than improvise — this task's choices are
expensive to reverse later.
