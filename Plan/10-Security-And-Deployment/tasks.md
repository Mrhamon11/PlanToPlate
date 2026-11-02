# 10 — Security Hardening & Deployment · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **10.1 — Object-level authorization sweep**
  Audit every viewset and view against the four-point checklist. Extend task 03's convention
  tests to cover every model added since. Fix what is found.
  *Files:* `core/tests/test_conventions.py`, `core/tests/test_authorization_sweep.py`, plus fixes
  in `meals/views.py`, `lists/views.py`, `catalog/views.py`
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

  **One item deferred here from task 05 review (non-blocking):** the recipe `flattened` /
  `scaled` API actions (and the `flatten` service) do not apply the "invisible component
  degrades gracefully" defence-in-depth that `RecipeSerializer` does. The share cascade should
  make an invisible sub-recipe/ingredient unreachable through a shared recipe, so this is not
  exploitable today — but `design.md` frames that degradation as cover "for the case where the
  cascade has a bug", and `flatten` leaks *more* than the serializer in that scenario (full
  nested ingredient list + every sub-recipe name via `FlatLine.from_recipes`). Add a
  sub-recipe/ingredient visibility check in `flatten` (or the actions) and a test.

- [x] **10.2 — Input validation sweep**
  Length caps on all text fields, bounds on decimals, validators on every user-writable field.
  *Files:* across all apps

- [x] **10.3 — Security headers**
  The prod settings block; `check --deploy` clean.
  Task 01 left `prod.py`'s `env("CACHE_DIR", default=…)` unpinned — only the cache `BACKEND` is
  asserted, so hardcoding `LOCATION` leaves the suite green. The throttle counters live in that
  cache, so it is worth an assertion while this subtask is in the file.
  *Files:* `config/settings/prod.py`

  **Resolved 2026-09-17 (10.15 rework — "next time this test helper is touched" arrived when
  `LOG_DIR` needed the identical treatment):** `config/tests/test_settings.py
  ::_import_settings_module` gained an `isolate_dirs: bool = True` parameter that points
  `CACHE_DIR` *and* `LOG_DIR` at a fresh temporary directory unless the caller already set one
  explicitly, so every subprocess-based settings test in the file (including this one's
  sibling helper, `config/tests/test_security_settings.py::_prod_settings`, which reuses the
  same function) now leaves the repo root untouched by default. The two tests that
  specifically exercise the real `BASE_DIR`-relative default
  (`test_prod_cache_location_defaults_under_base_dir`,
  `test_prod_log_dir_defaults_under_base_dir`) pass `isolate_dirs=False` and accept that one
  known, deliberate side effect. `test_deploy_check_clean` (a raw `subprocess.run` of
  `manage.py check --deploy`, not routed through the helper) now sets both env vars to
  `tmp_path` directly for the same reason — that one actually triggers a full `django.setup()`,
  which is what made this matter for `LOG_DIR`'s eagerly-created rotating file handlers in the
  first place, not just `CACHE_DIR`'s already-lazy directory.

- [x] **10.4 — Content Security Policy**
  `django-csp` with no `unsafe-inline`. Refactor out any inline handler rather than excusing it.
  *Files:* `config/settings/base.py`, templates
  *Done when:* the browser console shows zero CSP violations across every page.

- [x] **10.5 — Rate limiting**
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

  **Carried-forward review finding (task 10 review, 2026-09-17):** `accounts/throttling.py`'s
  comment above `PASSWORD_CHANGE_THROTTLE_SCOPE`/`_RATE` claims "a settings test pins" it
  against `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["password_change"]` — no such test exists
  (only the login scope is pinned that way, by
  `test_the_login_throttle_scope_lives_in_exactly_one_place`). Today the two literals agree
  ("5/min" both places) so this is not a live bug, but if they drift the DRF and
  Django-admin password-change paths would silently enforce different rates while sharing one
  cache bucket. Fix by adding the equivalent assertion to `config/tests/test_throttling.py`,
  or softening the comment to stop claiming coverage that isn't there.

  **Resolved 2026-09-17 (as a side effect of the blocking rework below):** the second follow-up
  review found this pair of literals was worse than out of sync risk — `PasswordChangeAPIView`'s
  DRF `ScopedRateThrottle` and the HTML view's `check_rate_limit` used incompatible list-pruning
  algorithms against the *same* cache key, corrupting the shared bucket and producing false 429s
  under interleaved use (see the blocking finding this file's review round recorded). Fixed by
  routing `PasswordChangeAPIView.post()` through `core.services.ratelimit.check_rate_limit`
  directly, the same call the HTML view already made, instead of DRF's `ScopedRateThrottle`.
  `accounts.throttling.PASSWORD_CHANGE_THROTTLE_SCOPE`/`_RATE` are now the *only* literal for
  this rate — `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["password_change"]` was removed from
  `config/settings/base.py` because nothing reads it any more, so there is no longer a second
  copy to drift or to pin a settings test against. New test:
  `config/tests/test_throttling.py::test_password_change_bucket_survives_interleaved_html_and_api_calls_over_time`.

- [x] **10.6 — Dependency audit**
  `pip-audit` wired into the Makefile; resolve or document anything it finds.
  *Files:* `Makefile`

  **Resolved 2026-09-17:** `make audit` runs `uv run --group dev --group prod --group postgres
  --with pip-audit pip-audit` — the scanner itself stays out of `pyproject.toml`/`uv.lock` (an
  ephemeral `--with` overlay), while the `--group` flags widen the scan to every dependency
  group the lockfile can produce, including the optional `postgres` driver nobody has opted
  into yet. Clean as of this run: "No known vulnerabilities found" against all three groups.

- [x] **10.7 — Production Docker Compose**
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

    **Resolved 2026-09-17 (entrypoint-tolerates approach):** the refusal's `CommandError` now
    carries `returncode=2` (`accounts/management/commands/bootstrap_admin.py`), distinguishing
    it from every other failure this command can raise. `docker-entrypoint.sh`'s
    `run_first_run_command_if_present` captures the real exit status (`|| rc=$?`, since `set
    -e` would otherwise abort before the check runs), writes no marker and logs a loud warning
    on that specific code, and still `exit`s (aborting startup) on any other nonzero — so a
    genuine failure still stops the container, but this one no longer crash-loops it. The
    manual-invocation contract is unchanged: `call_command` in tests still sees the
    `CommandError` and its message; only the process exit code differs, pinned by
    `test_bootstrap_admin_reports_username_clash`'s new `returncode == 2` assertion.
  - **The bootstrapped temp password persists in the Docker json-file log indefinitely**,
    because `compose.yaml` sets no `logging:` options — `docker compose logs app` replays it
    until the container is recreated. This is disclosed in the command's own output and in the
    README, so it is a known exposure rather than a defect, but the log rotation this subtask
    already promises is what bounds the window. Set it explicitly.

    **Resolved 2026-09-17:** `compose.prod.yaml`'s `app` service sets `logging: {driver:
    json-file, options: {max-size: 10m, max-file: "5"}}` (50MB total); `caddy` gets the same
    driver at a smaller `max-size: 10m, max-file: "3"`. `compose.yaml` (task 00's dev-oriented
    file) is left as-is — production log retention is this file's job.
  - **`bootstrap_admin`'s check-then-create is not serialised.** The idempotence probe and the
    username lookup both run outside any transaction or lock, so two concurrent runs with
    different `--username` values would both proceed; only the same-username race is caught,
    by the retained `IntegrityError` backstop (which is itself the one branch of that file with
    no test). Unreachable through the entrypoint, which runs the command once, under a marker,
    with no arguments — but worth closing if 10.7 ever parallelises startup.

    **Noted 2026-09-17, still not fixed — remains correctly deferred:** `compose.prod.yaml`
    does not parallelise startup; `docker-entrypoint.sh` still runs `seed_catalog` and
    `bootstrap_admin` serially, one at a time, with no arguments, exactly as before. The race
    stays unreachable through the entrypoint and is left open for whenever (if ever) that
    changes.

- [x] **10.7b — Image reproducibility and provenance**
  Base image pinned by digest, `uv sync --frozen`, build metadata (git SHA, build date) baked
  in as labels and surfaced on the admin dashboard.
  *Files:* `Dockerfile`, `compose.prod.yaml`
  *Done when:* the running app can tell you exactly which commit it was built from — the first
  question you ask when something is wrong in production, and unanswerable without it.

  **Resolved 2026-09-17:** base image digest pinning and `uv sync --frozen` were already in
  place from task 00 (D13/D14) — net-new here is build provenance. The `Dockerfile`'s runtime
  stage takes `ARG GIT_SHA=unknown` / `ARG BUILD_DATE=unknown`, sets them as both `LABEL
  org.opencontainers.image.revision` / `.created` (visible via `docker inspect`) and matching
  `ENV` vars (visible to the running process). `config/admin.py::build_info()` reads
  `os.environ`, wired into `dashboard_context()["build"]` and rendered on
  `templates/admin/plantoplate_index.html`. `compose.prod.yaml` passes both through as build
  args (`${GIT_SHA:-unknown}` / `${BUILD_DATE:-unknown}`, deliberately not read from `.env` —
  a value living there could go stale); `make docker-build-prod` computes them fresh from `git
  rev-parse --short HEAD` / `date -u` on every build.

- [x] **10.8 — Caddy configuration**
  TLS, static and media, security headers, health check, gzip.

  **Resolved 2026-09-17:** active health checking added (`health_uri /healthz/` inside the
  `reverse_proxy app:8000` block) — Caddy now stops routing to a Django process reporting
  unhealthy at any point, not only at container startup (Compose's own healthcheck only gates
  `depends_on: condition: service_healthy`). TLS and gzip were already present from task 00.
  Static/media: left served by WhiteNoise in-process rather than moved to Caddy — see the
  handoff report's "noticed but not covered" item; changing an already-settled, working
  architecture decision (`ARCHITECTURE.md`'s tech stack table names WhiteNoise explicitly) was
  judged out of scope for this pass. Security headers: left as Django's sole responsibility
  (`config/settings/prod.py` + `django-csp`, both already `check --deploy`-clean per 10.3/10.4)
  rather than duplicated at the Caddy layer, to avoid two places that can drift out of sync.

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

    **Resolved 2026-09-17 (structural half):**
    `test_header_up_forwarded_for_argument_is_remote_host` pins the exact argument
    (`{remote_host}`, rejecting any client-influenced substitution) and
    `test_header_up_targets_the_app_upstream` pins the enclosing block to
    `reverse_proxy app:8000`, rejecting a decoy block elsewhere in the file. **Not resolved:**
    a live behavioural check (actually running the pinned Caddy image against a real backend
    and observing the header it forwards) was judged out of scope for this pass — no Docker
    was available in this session to build or verify one, and standing one up correctly needs
    real network wiring (a container named `app` reachable from Caddy) that a quick addition
    risked getting subtly wrong with no way to confirm it here. The Docker-gated skip-when-
    absent behaviour, and the CI gap it implies, are also unchanged. Left as a genuine
    follow-up — see the handoff report.
  - **The X-Forwarded-For comments are factually inverted.** `Caddyfile` and
    `config/settings/prod.py` both claim Caddy *appends* an untrusted client's XFF; the pinned
    `caddy:2.10.2-alpine` *replaces* it, verified at runtime. The shipped Caddyfile therefore
    produces byte-identical upstream headers with or without `header_up`, and `NUM_PROXIES=1`
    is the load-bearing control. Correct the comments — and note that `header_up
    X-Forwarded-For {remote_host}` becomes actively harmful the day a `trusted_proxies` global
    option is added (e.g. fronting with Cloudflare), because it would overwrite the real client
    IP with the upstream load balancer's and collapse every client into one throttle bucket.

    **Resolved 2026-09-17:** both files' comments now state plainly that Caddy replaces (not
    appends), that the Caddyfile's `header_up` line is therefore currently redundant with
    Caddy's own default, and warn against adding `trusted_proxies` without first revisiting
    (or removing) that line. The same corrected framing was also carried into two test
    docstrings that repeated the old (wrong) claim —
    `config/tests/test_settings.py::test_prod_sets_num_proxies_for_throttle_ident` and
    `accounts/tests/test_security.py::test_throttle_survives_x_forwarded_for_rotation_when_num_proxies_configured`
    — neither test's assertions changed, only the prose explaining what they guard against.
  *Files:* `Caddyfile`, `config/tests/test_caddyfile.py`, `config/settings/prod.py`

- [x] **10.9 — Gunicorn configuration**
  2 workers × 4 gthread threads, timeouts, access logging.
  *Files:* `gunicorn.conf.py`

  **Resolved 2026-09-17:** `gunicorn.conf.py` (new, repo root) replaces the inline flags
  `docker-entrypoint.sh` used to pass on the command line — `workers=2`, `threads=4`,
  `worker_class="gthread"`, `timeout=60` / `graceful_timeout=30` (the watchdog outlives
  SQLite's own 5s `busy_timeout`; the graceful window matches `docker compose stop`),
  `accesslog`/`errorlog="-"` with request duration appended to the default combined format,
  `worker_tmp_dir="/dev/shm"`, jittered `max_requests` worker recycling, and `preload_app =
  False` pinned explicitly with a comment on why (forking a worker from a parent holding an
  open SQLite connection is unsafe). The entrypoint now runs
  `gunicorn config.wsgi:application --config gunicorn.conf.py` — one file a future systemd
  unit (10.10) can point at unchanged instead of a second, drifting copy of the same flags.
  Covered by `config/tests/test_gunicorn_conf.py`.

- [x] **10.10 — systemd alternative**
  Unit files plus install notes for a Docker-free VPS.
  *Files:* `deploy/systemd/*.service`, `docs/OPERATIONS.md`

  **Resolved 2026-09-17:** `deploy/systemd/plantoplate.service` runs the same
  `docker-entrypoint.sh` the Docker Compose path uses unmodified (`Type=simple`, since the
  script's own final `exec gunicorn` replaces its process image — systemd's PID tracking sees
  gunicorn directly), with `DATA_DIR=/var/lib/plantoplate` as the non-Docker equivalent of the
  named volume and `ProtectSystem=strict` / `ReadWritePaths` scoped to just that directory plus
  `staticfiles/`. `deploy/systemd/plantoplate-caddy.service` runs the official `caddy` binary
  directly against the project's own `Caddyfile` (one documented edit: `app:8000` ->
  `127.0.0.1:8000`, no Docker network here) for a distro with no packaged Caddy unit; a
  distro's own `caddy` package/unit is the preferred alternative where available. `docs/
  OPERATIONS.md` (new) carries the full install walkthrough — service accounts, `uv sync
  --frozen --no-dev --group prod`, `/etc/plantoplate/plantoplate.env`, `/var/lib/plantoplate`,
  the Caddyfile edit, `systemctl enable --now` — plus verification and update steps. It is
  marked partial at the top: the rest of the production runbook (first-boot sequence, `SECRET_
  KEY` rotation, Postgres migration, moving to a VPS, `database is locked`) is 10.16's job and
  lands in the same file next.

- [x] **10.11 — Backup script**
  `sqlite3 .backup`, gzip, checksum, retention pruning, off-box sync hook.
  *Files:* `deploy/backup.sh`, `deploy/backup.timer`
  *Done when:* it produces a verified, checksummed backup and prunes correctly.

  **Resolved 2026-09-17:** `deploy/backup.sh` backs up via SQLite's Online Backup API —
  deliberately `sqlite3.Connection.backup()` (Python's stdlib, same underlying mechanism the
  CLI's `.backup` dot-command wraps) rather than shelling out to the `sqlite3` CLI binary,
  which ships in neither the Docker image nor a bare VPS today and would be a new OS-level
  dependency for no safety gain over the stdlib equivalent — documented in the script's own
  header. Gzipped, `sha256sum`-checksummed, rotated into `hourly/` (kept 24h) / `daily/` (30d)
  / `weekly/` (1yr) tiers via hardlink-or-copy promotion, pruned by mtime every run.
  Off-box sync is an opt-in hook (`RCLONE_REMOTE` or `RSYNC_TARGET` env var; skipped with a log
  line if neither is set). `deploy/backup.service` (oneshot) + `deploy/backup.timer` (hourly,
  `Persistent=true`) schedule it under systemd; `docs/OPERATIONS.md` covers the Docker-cron
  equivalent. Verified for real against the project's own dev `db.sqlite3` during
  implementation (see the handoff report), not just against synthetic fixtures.
  Tests: `deploy/tests/test_backup.py`.

- [x] **10.12 — Nightly `dumpdata` export**
  Engine-independent JSON insurance.
  *Files:* `deploy/backup.sh`

  **Resolved 2026-09-17:** folded into `deploy/backup.sh` rather than a second script — one
  pipeline, `--skip-dumpdata` to opt out. `manage.py dumpdata --natural-foreign
  --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions
  --indent 2`, gzipped and checksummed into `DUMPDATA_DIR` (default `$BACKUP_DIR/dumpdata`),
  pruned at `DUMPDATA_RETENTION_DAYS` (default 30). The exclusions keep the export loadable
  into a fresh database whose own `migrate` already populated its own contenttypes/permissions
  rather than fighting over primary keys for auto-generated bookkeeping rows. Proven to
  round-trip (`dumpdata` -> fresh migrated DB -> `loaddata`) both in
  `deploy/tests/test_backup.py::test_dumpdata_export_loads` and for real against the dev
  database during implementation.

- [x] **10.13 — Restore drill**
  `make restore-test` restoring into a scratch directory and comparing object counts.
  **Actually run it.**
  *Files:* `Makefile`, `deploy/restore-test.sh`

  **Resolved 2026-09-17:** `deploy/restore-test.sh` restores the newest (or a named) backup
  into a scratch directory, verifies its checksum and `PRAGMA integrity_check`, runs `manage.py
  migrate` against the restored copy (design.md's "restore, then migrate" edge case, in that
  order), then compares every real table's row count against the live source (`django_
  migrations` excluded — Django's own bookkeeping, and expected to diverge exactly when the
  restore-then-migrate step it is testing applies a migration the live source has not received
  yet, which is not a data-loss signal). `make restore-test` runs `make backup` first, then the
  drill, against this checkout's own `db.sqlite3`. **Actually run**, twice: once by hand
  against the real dev-test dataset (`db.sqlite3`, ~39 recipes / 25 dishes / 176 ingredients —
  every table matched, `RESULT PASS`) and once via the exact commands the Makefile target
  itself runs — `make` is not installed in this implementation sandbox, so the target's exact
  invocation was run directly rather than through `make`; the Makefile syntax (tabs, `$(CURDIR)`)
  was verified by inspection and matches the rest of the file. Worth a bare `make restore-test`
  spot-check on a machine that has `make`. Tests: `deploy/tests/test_restore.py`.

- [x] **10.14 — WAL checkpoint maintenance**
  Periodic `wal_checkpoint(TRUNCATE)`.
  *Files:* `core/management/commands/checkpoint_wal.py`

  **Resolved 2026-09-17:** `manage.py checkpoint_wal [--database ALIAS]` runs `PRAGMA
  wal_checkpoint(TRUNCATE)`, reporting success, a `busy` result (a concurrent writer held a
  lock — expected under real traffic, logged as a warning, not raised as an error, so a
  scheduled run never spuriously alerts) or a clean no-op against a non-SQLite alias (Postgres
  portability). The actual pragma runs through `core.services.wal.checkpoint_truncate`'s own
  independent `sqlite3.connect()` rather than Django's connection/cursor machinery for the
  alias — see that module's docstring; this also made the command trivially unit-testable
  without touching `config.settings.test`'s shared `:memory:` "default" alias, which a real
  Django-connection-based checkpoint would have required closing/repointing and, being
  in-memory, would have destroyed for the rest of the test session. `docs/OPERATIONS.md`
  documents scheduling it (systemd timer template, or cron inside the container for Docker).
  Tests: `core/tests/test_ops.py`.

- [x] **10.15 — Logging configuration**
  Rotating file handlers, separate error log, no secrets, optional Sentry seam.
  *Files:* `config/settings/prod.py`

  **Resolved 2026-09-17:** `config/settings/prod.py::_logging_config(log_dir)` builds two
  rotating handlers (`app.log` at `INFO`+, `error.log` at `ERROR`+ only, 10 MB x 5 backups
  each) plus the existing console handler, under an env-overridable `LOG_DIR` (default
  `BASE_DIR / "logs"`, mirroring `CACHE_DIR`'s existing pattern; `compose.prod.yaml` points it
  at the persistent data volume). Extracted into a function rather than inlined so
  `core/tests/test_ops.py::test_logging_excludes_passwords` (now implemented for real — the
  module docstring's "not yet implemented" note is gone) can build the identical handler
  config against a scratch directory and read the files it actually writes. Optional Sentry
  seam: `SENTRY_DSN` from env, off by default (empty = complete no-op, `sentry_sdk` never
  imported); `sentry-sdk` is deliberately **not** added as a dependency (CLAUDE.md requires
  permission to add one, and no deployment has asked for it yet) — setting `SENTRY_DSN` with
  the package not installed fails loudly (`ImproperlyConfigured`) rather than silently running
  with no error reporting. New tests in `config/tests/test_settings.py`
  (`test_prod_log_dir_follows_env_var`, `test_prod_log_dir_defaults_under_base_dir`,
  `test_prod_logging_has_rotating_app_and_error_files`,
  `test_prod_logging_sentry_seam_is_off_by_default`,
  `test_prod_logging_sentry_dsn_without_package_fails_loudly`).

- [x] **10.16 — Operations runbook**
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

  **Resolved 2026-09-17:** `docs/OPERATIONS.md`'s "Production first deployment" section now
  spells out exactly when a deployer needs to set `CSRF_TRUSTED_ORIGINS` (a second hostname
  answering the same app, or a reverse proxy in front of Caddy that rewrites `Host`) and what
  it looks like when set. The accepted deviation itself is recorded in `ARCHITECTURE.md`'s
  decision log as D58.

- [x] **10.17 — Deployment rehearsal**
  Deploy to a clean target, run the smoke checklist, restore a backup into it.
  *Files:* notes in `docs/OPERATIONS.md`

  **Resolved 2026-09-17 (with an honest gap):** full results for all 14 manual verifications
  are recorded in `docs/OPERATIONS.md`'s "Deployment rehearsal (10.17) — results" section.
  Summary: checks 1–6 (Docker deployment itself, browsing every page with devtools) **could
  not be exercised** — this implementation sandbox has neither Docker nor a browser, the same
  disclosed limit as 10.7's live Caddy check and 10.13's `make`-unavailable restore drill; this
  is a real follow-up for whoever next has Docker access, not a closed item. The specific
  carried-forward finding this subtask owned — CSP against admin `autocomplete_fields`
  pages — **was** exercised (no browser needed for the method used: rendering
  `IngredientAdmin`/`RecipeAdmin`/`DishAdmin`/`MealPlanProfileAdmin`'s add forms through
  Django's real request/response cycle and inspecting the actual headers/HTML, plus a static
  read of the vendored select2 JS/CSS Django ships) — **PASS**, with the residual gap (no real
  browser CSP-enforcement confirmation) stated plainly rather than closed. Checks 7–9 (backup
  produces a valid checksummed file, a real restore matches, retention prunes correctly) were
  run for real against a **scratch copy** of the dev database (never the live `db.sqlite3`,
  per CLAUDE.md's script-testing rule) — PASS. Check 10 (off-box copy lands off-box) could not
  be verified live (no real remote configured in this sandbox) — unit-tested with a stub, but
  a genuine remote-lands-off-box confirmation is a follow-up for whoever configures a real
  destination. Checks 11–14 (admin access denied for a regular user, private recipe 404 not
  403, login throttle 429, secure/httponly/samesite cookie) were all run live against the real
  view/permission/serializer stack — PASS.

  **Added 2026-09-17 (task 10 review):** when checks 1–6 are finally exercised on a real
  Docker host, also confirm `compose.prod.yaml`'s `deploy.resources.limits`/`reservations`
  on the `app`/`caddy` services actually apply under plain `docker compose up` (non-swarm) —
  e.g. `docker inspect` showing the memory/cpu limits on the running containers. Modern
  Compose V2 is expected to translate `deploy` outside swarm, but this was never verified live
  in the implementation sandbox (no Docker available). Don't close the checks 1–6 gap without
  this confirmation too.

  **Closed 2026-11-01 (owner-run live rehearsal on Docker 29 / Fedora, SELinux enforcing):**
  checks 1–6 and 10 were run for real on a clean-volume deployment over the tailnet; results and
  the seven defects it found (all fixed, D59–D61) are in `docs/OPERATIONS.md` "Live rehearsal
  results". Resource limits confirmed applied (`app` 768M / 256M reserved / 2.0 CPU, `caddy`
  256M / 1.0 CPU). Remaining honest gaps: check 4 was a Docker-daemon restart, not a host
  reboot; check 10 landed on a local directory, not a remote host (SSH keys to the homelab are
  not set up yet); check 6 has no `securityheaders.com` grade because a tailnet-only site cannot
  be fetched, so headers were inspected by hand. Browser console findings that are not CSP were
  moved to task 11 (11.35, 11.36).

- [x] **10.18 — Update the living document**
  Task 10 → AWAITING APPROVAL. **MVP complete.**
  *Files:* `Plan/MILESTONES.md`
