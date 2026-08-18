# 00 — Foundations · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Work in order. Each subtask leaves the tree in a working state.

- [x] **00.1 — Initialize the uv project**
  `pyproject.toml` with project metadata and the dependency groups from the design.
  *Files:* `pyproject.toml`, `uv.lock`, `.python-version`
  *Done when:* `uv run python -c "import django; print(django.get_version())"` prints 5.1+.

- [x] **00.2 — Django project scaffold**
  `uv run django-admin startproject config .`, then restructure `settings.py` into
  `config/settings/{__init__,base,dev,prod,test}.py`.
  *Files:* `manage.py`, `config/**`
  *Done when:* `uv run manage.py check` passes under dev settings.

- [x] **00.3 — Environment configuration**
  `django-environ` wired in; `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` all from
  env. Commit `.env.example`, gitignore `.env`.
  *Files:* `config/settings/base.py`, `.env.example`, `.gitignore`
  *Done when:* starting with no `SECRET_KEY` raises `ImproperlyConfigured` rather than falling back.

- [x] **00.4 — SQLite concurrency configuration**
  The conditional pragma / `transaction_mode` block from the design.
  *Files:* `config/settings/base.py`
  *Done when:* a shell query confirms `PRAGMA journal_mode` returns `wal`.

- [x] **00.5 — App skeletons**
  Create and register `core`, `accounts`, `catalog`, `recipes`, `meals`, `lists`, `planner`,
  each with an explicit app `label` and an empty `tests/` package.
  *Files:* seven app directories, `config/settings/base.py`
  *Done when:* `manage.py check` is clean with all seven installed.

- [x] **00.6 — DRF and API docs**
  DRF, `django-filter`, `drf-spectacular`. Default permission `IsAuthenticated`, default
  pagination, schema at `/api/schema/`, Swagger at `/api/docs/`.
  *Files:* `config/settings/base.py`, `config/urls.py`
  *Done when:* `/api/docs/` renders for an authenticated user (see decision D12 — the schema
  and docs are not anonymous).

  > Default-deny on permissions is deliberate. An endpoint added later that forgets its
  > permission class should fail closed, not open.

- [x] **00.7 — Test infrastructure**
  pytest + pytest-django + factory_boy + coverage. Root `conftest.py` with `api_client`,
  `user_factory`, and `authenticated_client`.
  *Files:* `pyproject.toml`, `conftest.py`, `config/settings/test.py`
  *Done when:* `uv run pytest` runs and reports zero failures.

- [x] **00.8 — Linting**
  ruff configured for lint and format; fix everything it flags in the scaffold.
  *Files:* `pyproject.toml`
  *Done when:* `ruff check .` and `ruff format --check .` both pass.

- [x] **00.9 — Health check endpoint**
  `GET /healthz/` with a real database round-trip, exempt from authentication.
  *Files:* `core/views.py`, `core/urls.py`, `config/urls.py`
  *Done when:* it returns 200 with both keys `ok`.

- [x] **00.10 — Dockerfile**
  Multi-stage, non-root, `uv sync --frozen --no-dev`, base image pinned by digest, and the
  system packages Pillow needs installed in the **runtime** stage.
  *Files:* `Dockerfile`, `.dockerignore`
  *Done when:* the image builds and `.dockerignore` excludes `.venv`, `db.sqlite3`, `.env`,
  and `media/` — verified by inspecting the build context, since baking a local database or
  `.env` into a layer leaks data and secrets into the image.

- [x] **00.11 — Container entrypoint**
  `docker-entrypoint.sh` running migrate, collectstatic, first-run-only seed and
  `bootstrap_admin`, then `exec gunicorn`.
  *Files:* `docker-entrypoint.sh`
  *Done when:* a container started against an **empty volume** comes up fully working — schema
  applied, catalog seeded, admin created with its temp password printed once to the logs — and
  a restart re-seeds nothing.

  > `exec` matters: without it gunicorn is not PID 1, does not receive `SIGTERM`, and gets
  > force-killed on `docker compose stop` — which on SQLite risks stopping mid-write.

- [x] **00.12 — Compose stack**
  App plus Caddy, named volumes for database and media, `restart: unless-stopped`, and a
  `healthcheck:` on `/healthz/`. Postgres service present but commented out.
  *Files:* `compose.yaml`, `Caddyfile`
  *Done when:* `docker compose up` on a clean machine serves the app, and the database survives
  `docker compose restart` and `docker compose down && up`.

- [x] **00.13 — Makefile**
  Targets: `install`, `run`, `test`, `lint`, `fmt`, `check`, `migrate`, `shell`, `secret`,
  `docker-build`, `docker-up`, `docker-logs`.
  *Files:* `Makefile`
  *Done when:* every target runs. `make secret` prints a fresh `SECRET_KEY` for `.env`.

- [x] **00.14 — First-deployment documentation**
  The complete from-nothing path in the README: clone, `cp .env.example .env`, `make secret`,
  `docker compose up`, log in with the printed temp password.
  *Files:* `README.md`
  *Done when:* someone following it on a clean machine reaches a working login screen without
  needing any step that is not written down.

- [x] **00.15 — Update the living document**
  Task 00 → AWAITING APPROVAL; record any decision made here.
  *Files:* `Plan/MILESTONES.md`
