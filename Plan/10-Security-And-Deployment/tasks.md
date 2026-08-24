# 10 — Security Hardening & Deployment · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **10.1 — Object-level authorization sweep**
  Audit every viewset and view against the four-point checklist. Extend task 03's convention
  tests to cover every model added since. Fix what is found.
  *Files:* `core/tests/test_conventions.py`, plus fixes
  *Done when:* every owned model is covered by the automated convention test.

  **Two unpinned invariants deferred here from task 01** — both are correct in the code and
  neither is exploitable; what is missing is a test that would notice if they stopped being
  correct:
  - `ForcePasswordChangeMiddleware._is_exempt` matches exempt paths **exactly**, and design.md
    forbids a prefix match by name ("a prefix match would also exempt `/api/auth/me/`").
    Loosening it to a `/api/auth/` prefix leaves the whole suite green, because
    `ForcePasswordChangeAPIPermission` independently blocks the same requests — defence in
    depth is working, but the named invariant has no guard of its own. One assertion that
    `_is_exempt("/api/auth/me/")` is `False` closes it.
  - `GET /admin/login/` is untested: making `throttled_admin_login` return an empty 200 for
    non-POST leaves the suite green. One `client.get("/admin/login/")` asserting 200 and a
    form in the body closes it.

- [ ] **10.2 — Input validation sweep**
  Length caps on all text fields, bounds on decimals, validators on every user-writable field.
  *Files:* across all apps

- [ ] **10.3 — Security headers**
  The prod settings block; `check --deploy` clean.
  Task 01 left `prod.py`'s `env("CACHE_DIR", default=…)` unpinned — only the cache `BACKEND` is
  asserted, so hardcoding `LOCATION` leaves the suite green. The throttle counters live in that
  cache, so it is worth an assertion while this subtask is in the file.
  *Files:* `config/settings/prod.py`

- [ ] **10.4 — Content Security Policy**
  `django-csp` with no `unsafe-inline`. Refactor out any inline handler rather than excusing it.
  *Files:* `config/settings/base.py`, templates
  *Done when:* the browser console shows zero CSP violations across every page.

- [ ] **10.5 — Rate limiting**
  Throttles on password change, admin actions, import, and a global authenticated default.

  **Three items deferred here from task 01's login throttle (01.8):**
  - **The shared login budget is per-identity, not per-IP.** `ScopedRateThrottle.get_cache_key`
    keys on `request.user.pk` when the request is authenticated and falls back to IP only when
    anonymous, so an attacker holding any one valid account gets a second full 5/min budget
    from the same IP — 10/min, plus 5 more per additional account they control. Measured on
    both the HTML and admin login paths. The design's actual invariant (endpoint-switching
    cannot multiply the budget) still holds. Fix by keying the login scope on IP
    unconditionally, or by resetting the counter on successful authentication.
  - **A successful login still spends from the bucket**, so a household behind one NAT address
    can throttle itself out. The same fix closes both.
  - **`Retry-After` on the two Django-rendered 429s is unpinned** — deleting the `wait` /
    `Retry-After` block in `check_login_throttle` leaves the suite green. Pin it here, since
    10's checklist already promises live-verified throttles.
  *Files:* `config/settings/base.py`, `accounts/throttling.py`, viewsets

- [ ] **10.6 — Dependency audit**
  `pip-audit` wired into the Makefile; resolve or document anything it finds.
  *Files:* `Makefile`

- [ ] **10.7 — Production Docker Compose**
  Restart policies, resource limits, log rotation, healthcheck. Reuses task 00's entrypoint;
  do not fork a second startup path.
  *Files:* `compose.prod.yaml`
  *Done when:* a clean-volume production deploy comes up working, and resource limits are low
  enough that a runaway request cannot take the whole server down.

  **Two items deferred here from task 01:**
  - **`bootstrap_admin` can crash-loop the container.** 01.9 added an `is_active=True` clause
    to the idempotence probe, which turned the "a disabled or non-admin account already holds
    this username" case from a graceful exit-0 skip into a `CommandError` (exit 1). Under the
    entrypoint's `set -euo pipefail` that aborts before `exec gunicorn`; `restart:
    unless-stopped` makes it a loop, and Caddy's `depends_on: service_healthy` means the site
    never binds. Reachable only when `.ran-bootstrap_admin` is absent while the database still
    holds an unusable `admin` — a database-only restore, the documented Postgres switch, or an
    operator deleting the marker to force a re-run, all of which are exactly the recovery
    paths 10.16 documents. Either have the entrypoint tolerate this specific refusal, or have
    the command exit 0 with a loud warning when the refusal is the recoverable kind.
  - **The bootstrapped temp password persists in the Docker json-file log indefinitely**,
    because `compose.yaml` sets no `logging:` options — `docker compose logs app` replays it
    until the container is recreated. This is disclosed in the command's own output and in the
    README, so it is a known exposure rather than a defect, but the log rotation this subtask
    already promises is what bounds the window. Set it explicitly.
  - **`bootstrap_admin`'s check-then-create is not serialised.** The idempotence probe and the
    username lookup both run outside any transaction or lock, so two concurrent runs with
    different `--username` values would both proceed; only the same-username race is caught,
    by the retained `IntegrityError` backstop (which is itself the one branch of that file with
    no test). Unreachable through the entrypoint, which runs the command once, under a marker,
    with no arguments — but worth closing if 10.7 ever parallelises startup.

- [ ] **10.7b — Image reproducibility and provenance**
  Base image pinned by digest, `uv sync --frozen`, build metadata (git SHA, build date) baked
  in as labels and surfaced on the admin dashboard.
  *Files:* `Dockerfile`, `compose.prod.yaml`
  *Done when:* the running app can tell you exactly which commit it was built from — the first
  question you ask when something is wrong in production, and unanswerable without it.

- [ ] **10.8 — Caddy configuration**
  TLS, static and media, security headers, health check, gzip.

  **Two items deferred here from task 01:**
  - **`config/tests/test_caddyfile.py` is weaker than its docstring.** It asserts only that
    *some* `header_up` line sits inside *some* `reverse_proxy` block; it checks neither the
    directive's argument nor which proxy carries it. Two Caddyfiles that are broken in
    production pass both this test and `caddy validate`: `header_up X-Forwarded-For
    {http.request.header.X-Forwarded-For}` (a total throttle bypass — the client writes the
    whole header, and a client sending none keys every request on the empty string, which is
    also a trivial DoS), and a decoy `handle /unused/*` block holding the correct directive
    while the real proxy has none. Assert the argument is `{remote_host}`, assert it is on the
    proxy fronting `app:8000`, and prefer a live behavioural check over a structural one. Note
    also that the container-backed validity test skips silently when Docker is absent and
    there is no CI, so today nothing catches a syntax error elsewhere in the file.
  - **The X-Forwarded-For comments are factually inverted.** `Caddyfile` and
    `config/settings/prod.py` both claim Caddy *appends* an untrusted client's XFF; the pinned
    `caddy:2.10.2-alpine` *replaces* it, verified at runtime. The shipped Caddyfile therefore
    produces byte-identical upstream headers with or without `header_up`, and `NUM_PROXIES=1`
    is the load-bearing control. Correct the comments — and note that `header_up
    X-Forwarded-For {remote_host}` becomes actively harmful the day a `trusted_proxies` global
    option is added (e.g. fronting with Cloudflare), because it would overwrite the real client
    IP with the upstream load balancer's and collapse every client into one throttle bucket.
  *Files:* `Caddyfile`, `config/tests/test_caddyfile.py`, `config/settings/prod.py`

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
