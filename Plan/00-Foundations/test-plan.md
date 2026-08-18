# 00 — Foundations · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

This task is infrastructure, so the tests assert that the *configuration* is correct. They are
cheap to write and they catch the class of bug that otherwise only shows up in production.

## Configuration — `config/tests/test_settings.py`

| Test | Asserts |
|---|---|
| `test_secret_key_required` | Loading settings without `SECRET_KEY` raises `ImproperlyConfigured`. No silent fallback — a defaulted secret key means forgeable sessions. |
| `test_debug_false_in_prod` | `prod.py` has `DEBUG is False`. |
| `test_sqlite_pragmas_applied` | A live connection reports `journal_mode == "wal"` and `foreign_keys == 1`. |
| `test_sqlite_options_skipped_for_postgres` | With `DATABASE_URL` pointing at Postgres, no SQLite `OPTIONS` are attached. Guards the portability promise. |
| `test_database_url_override` | Setting `DATABASE_URL` changes the resolved database. |
| `test_prod_security_flags` | Under prod: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT` True, HSTS set. |
| `test_drf_defaults_deny_by_default` | DRF's default permission class is `IsAuthenticated`. |

## Health check — `core/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_healthz_returns_ok` | 200 with `{"status": "ok", "database": "ok"}`. |
| `test_healthz_no_auth_required` | Reachable unauthenticated. |
| `test_healthz_reports_db_failure` | With the connection patched to raise, returns 503 and `database: "error"`. A health check that cannot detect an unhealthy database is decoration. |

## Structure — `core/tests/test_project_structure.py`

| Test | Asserts |
|---|---|
| `test_all_apps_installed` | All seven app labels present in `INSTALLED_APPS`. |
| `test_no_pending_migrations` | `makemigrations --check --dry-run` exits clean. Catches the "forgot to generate the migration" failure on every future task. |
| `test_api_schema_renders` | `/api/schema/` returns 200 and valid OpenAPI. |

## Fixtures — `tests/test_conftest.py`

| Test | Asserts |
|---|---|
| `test_user_factory_creates_user` | Produces a persisted user with a usable password. |
| `test_authenticated_client_is_authenticated` | Requests through the fixture arrive authenticated. |

## Manual verification

Not automated; the implementer performs these and reports the results.

1. `uv run manage.py runserver` → `/healthz/` and `/api/docs/` both load.
2. `DJANGO_SETTINGS_MODULE=config.settings.prod uv run manage.py check --deploy` →
   **zero warnings**. Warnings under dev settings are expected and fine.
3. **Clean-machine deploy.** From a fresh clone with **no existing volume**:
   `cp .env.example .env && make secret && docker compose up`. Confirm the app comes up with
   the schema applied, the catalog seeded, and an admin temp password printed once in the logs.
   This is the out-of-the-box claim being tested rather than assumed.
4. `docker compose restart` and `docker compose down && docker compose up` → data survives both.
5. Restart again and confirm the entrypoint does **not** re-seed or create a second admin.
6. `docker compose stop` → confirm a graceful shutdown in the logs, not a force-kill. On SQLite
   a force-kill mid-write is how a database gets corrupted.
7. Inspect the built image: `docker run --rm <image> ls -a /app` shows no `db.sqlite3`, no
   `.env`, no `.venv`.
8. Point `DATABASE_URL` at a scratch Postgres and run `migrate`. This tests the portability
   claim for real instead of asserting it in a comment.

## Definition of Done

- [ ] `uv run pytest` — all green, no skips.
- [ ] `ruff check .` and `ruff format --check .` — clean.
- [ ] `manage.py check --deploy` under **prod** settings — zero warnings.
- [ ] `makemigrations --check` — nothing pending.
- [ ] A **clean-machine deploy against an empty volume** comes up fully working with no manual
      step beyond `.env` + `make secret` (manual checks #3–#5).
- [ ] Data survives restart and `down`/`up`; shutdown is graceful.
- [ ] No database, `.env`, or `.venv` is baked into the image (manual check #7).
- [ ] The Postgres migration run in Manual Verification #8 succeeded.
- [ ] `README.md` documents the full from-nothing deployment path.
- [ ] `.env` gitignored, `.env.example` committed, no secret in any tracked file.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
