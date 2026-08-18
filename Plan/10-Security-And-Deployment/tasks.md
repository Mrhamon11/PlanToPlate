# 10 — Security Hardening & Deployment · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **10.1 — Object-level authorization sweep**
  Audit every viewset and view against the four-point checklist. Extend task 03's convention
  tests to cover every model added since. Fix what is found.
  *Files:* `core/tests/test_conventions.py`, plus fixes
  *Done when:* every owned model is covered by the automated convention test.

- [ ] **10.2 — Input validation sweep**
  Length caps on all text fields, bounds on decimals, validators on every user-writable field.
  *Files:* across all apps

- [ ] **10.3 — Security headers**
  The prod settings block; `check --deploy` clean.
  *Files:* `config/settings/prod.py`

- [ ] **10.4 — Content Security Policy**
  `django-csp` with no `unsafe-inline`. Refactor out any inline handler rather than excusing it.
  *Files:* `config/settings/base.py`, templates
  *Done when:* the browser console shows zero CSP violations across every page.

- [ ] **10.5 — Rate limiting**
  Throttles on password change, admin actions, import, and a global authenticated default.
  *Files:* `config/settings/base.py`, viewsets

- [ ] **10.6 — Dependency audit**
  `pip-audit` wired into the Makefile; resolve or document anything it finds.
  *Files:* `Makefile`

- [ ] **10.7 — Production Docker Compose**
  Restart policies, resource limits, log rotation, healthcheck. Reuses task 00's entrypoint;
  do not fork a second startup path.
  *Files:* `compose.prod.yaml`
  *Done when:* a clean-volume production deploy comes up working, and resource limits are low
  enough that a runaway request cannot take the whole server down.

- [ ] **10.7b — Image reproducibility and provenance**
  Base image pinned by digest, `uv sync --frozen`, build metadata (git SHA, build date) baked
  in as labels and surfaced on the admin dashboard.
  *Files:* `Dockerfile`, `compose.prod.yaml`
  *Done when:* the running app can tell you exactly which commit it was built from — the first
  question you ask when something is wrong in production, and unanswerable without it.

- [ ] **10.8 — Caddy configuration**
  TLS, static and media, security headers, health check, gzip.
  *Files:* `Caddyfile`

- [ ] **10.9 — Gunicorn configuration**
  2 workers × 4 gthread threads, timeouts, access logging.
  *Files:* `gunicorn.conf.py`

- [ ] **10.10 — systemd alternative**
  Unit files plus install notes for a Docker-free VPS.
  *Files:* `deploy/systemd/*.service`, `docs/OPERATIONS.md`

- [ ] **10.11 — Backup script**
  `sqlite3 .backup`, gzip, checksum, retention pruning, off-box sync hook.
  *Files:* `deploy/backup.sh`, `deploy/backup.timer`
  *Done when:* it produces a verified, checksummed backup and prunes correctly.

- [ ] **10.12 — Nightly `dumpdata` export**
  Engine-independent JSON insurance.
  *Files:* `deploy/backup.sh`

- [ ] **10.13 — Restore drill**
  `make restore-test` restoring into a scratch directory and comparing object counts.
  **Actually run it.**
  *Files:* `Makefile`, `deploy/restore-test.sh`

- [ ] **10.14 — WAL checkpoint maintenance**
  Periodic `wal_checkpoint(TRUNCATE)`.
  *Files:* `core/management/commands/checkpoint_wal.py`

- [ ] **10.15 — Logging configuration**
  Rotating file handlers, separate error log, no secrets, optional Sentry seam.
  *Files:* `config/settings/prod.py`

- [ ] **10.16 — Operations runbook**
  Every procedure in the design. Extends task 00's `README.md` (which covers first local
  deployment) with the production path; the README links to it rather than duplicating it.

  The **production first-boot sequence** must be written out step by step, copy-pasteable,
  assuming nothing:
  1. Clone, `cp .env.example .env`.
  2. `make secret` → paste the generated `SECRET_KEY` into `.env`. **State plainly that the app
     will refuse to start without it, and that losing or changing it later logs every user out.**
  3. Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and the Caddy hostname for the real domain or
     Tailscale name.
  4. `docker compose -f compose.prod.yaml up -d`.
  5. Retrieve the admin temp password from the container logs — **printed once**, so capture it
     before the logs rotate.
  6. Log in, complete the forced password change, verify `/healthz/`.
  7. Run the first backup and **immediately test-restore it** (10.13) before putting real data in.

  Also: updating a running deployment, rolling back to a previous image, rotating `SECRET_KEY`,
  restoring from backup, migrating to Postgres, moving to a VPS, and what to do when SQLite
  reports `database is locked`.
  *Files:* `docs/OPERATIONS.md`, `README.md`
  *Done when:* someone who has never seen the project can follow it start to finish on a clean
  server and reach a working login screen without asking a question.

- [ ] **10.17 — Deployment rehearsal**
  Deploy to a clean target, run the smoke checklist, restore a backup into it.
  *Files:* notes in `docs/OPERATIONS.md`

- [ ] **10.18 — Update the living document**
  Task 10 → AWAITING APPROVAL. **MVP complete.**
  *Files:* `Plan/MILESTONES.md`
