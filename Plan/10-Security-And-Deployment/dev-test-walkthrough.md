# 10 — Security & Deployment · Manual dev-test walkthrough

> Scratch file for the human dev-test pass. Unlike tasks 08/09/12, this one **is** part of the
> Definition of Done — `test-plan.md`'s 14-item "Manual verification" section is mandatory, and
> the implementation sandbox had no Docker daemon and no browser, so checks 1–6 and 10 were
> never actually run against a real container. This file is the instrument that closes that
> gap for real, plus gives task 10 the same confidence-building click-through the other three
> tasks got.

Two tracks, because the 14 checks split cleanly by what they need:

- **Track A — no Docker required** (checks 11–14, plus `manage.py check --deploy` and the
  backup/restore drill, checks 7–9): run directly on `fedora-headless` against the existing
  dev-test dataset via `uv run manage.py runserver`, with `DJANGO_SETTINGS_MODULE` swapped to
  `config.settings.prod` only for the specific steps that need `DEBUG=False`.
- **Track B — needs a Docker host** (checks 1–6, check 10, and the two carried-forward items
  from `tasks.md` 10.8 and 10.17): needs a clean-volume `compose.prod.yaml` deploy on a machine
  that actually has Docker. `fedora-headless` does not, as of this walkthrough — see Setup.

---

## Setup

### What this machine actually has (checked 2026-09-17)

- **No `docker`, no `docker compose`, no `make`** on `fedora-headless` — all three commands
  come back "command not found." The dev-test topology memory said this box runs the app via
  plain `uv run manage.py runserver`, and that is still true.
- `df -h /` shows 9.5G free of 15G — plenty of headroom for a Docker install and a rehearsal
  stack (this app's image and a SQLite database are small).
- `.env` and `db.sqlite3` already exist in this checkout (the dev-test dataset from tasks
  08/09/12: `ALLOWED_HOSTS` already includes `fedora-headless.scorpion-tench.ts.net`,
  `SECRET_KEY` is already set, `SITE_ADDRESS` already names this box). **Do not point Track B's
  clean-volume rehearsal at this same `.env`/checkout** — see "Choosing a Docker target" below.
- `db.sqlite3` is 5 migrations behind current `HEAD` (`catalog.0003`, `lists.0002`,
  `meals.0003`, `planner.0004`, `recipes.0005` — the same gap `docs/OPERATIONS.md`'s 10.17
  results section already noticed). Run `uv run manage.py migrate` before Track A if you want
  the running dev server itself to be on the current schema — the migration is additive
  (`max_length` tightenings from this task's input-validation sweep) and safe to apply to the
  live dev-test database; the backup/restore checks below don't require it since
  `restore-test.sh` already exercises "restore, then migrate" as part of what it verifies.
- `tailscale status` shows two other **online** Linux boxes on the tailnet:
  `fedora-server` and `nobara-server`. Neither has SSH access set up from this box (matches the
  dev-test-topology memory — password/key auth both refused when checked), so their Docker
  status could not be verified from here. If you have direct access to either, check `which
  docker && docker compose version` there before assuming it's a candidate for Track B — don't
  assume a box has Docker just because it's on the tailnet and awake.

### Choosing a Docker target for Track B

Pick **one** of:

1. **Install Docker + Compose on `fedora-headless` itself**, in a **separate directory** from
   this dev-test checkout (e.g. `~/git/PlanToPlate-rehearsal`, a fresh `git clone`) so Compose's
   project-name-based volume namespacing gives the rehearsal its own `plantoplate_data` /
   `plantoplate_media` volumes, never touching the dev-test `db.sqlite3` or `.env` above.
   Fedora's own package (`sudo dnf install docker docker-compose-plugin`, then `sudo systemctl
   enable --now docker` and add your user to the `docker` group) or Docker's official repo both
   work — this walkthrough does not install it for you (out of scope per the dispatch), just
   flags that it's the missing prerequisite.
2. **Use `fedora-server` or `nobara-server`** if either already has Docker and you're
   comfortable running a throwaway container stack there. Clone the repo fresh there too — same
   clean-volume reasoning as above.
3. **Any other machine with Docker** you control — a laptop, a cloud VM. The only requirements:
   it can reach this repo (or a clone of it), and you can reach *it* afterward to browse the
   rehearsal deployment and run `docker inspect` / `docker compose logs` against it.

Whichever you pick, this is a **from-scratch rehearsal**, not a copy of the dev-test data — the
whole point of "clean volume" (test-plan.md check 1, design.md's Docker Compose path) is proving
first boot works on nothing, the way a real new deployment would. Do not copy `db.sqlite3` or
`.env` from this checkout onto it.

### Credentials note for Track A

Track A reuses the existing dev-test accounts (`hamon`, `avi`, `alice` — same as tasks 08/09/12).
If you don't have `hamon`'s current password, `uv run manage.py bootstrap_admin --force
--username hamon` mints a fresh one-time temp password on this box (the documented recovery
route from `README.md`).

---

## Track A — no Docker needed

### Scenario A1 — `manage.py check --deploy` is clean

```bash
mkdir -p /tmp/p2p10-cache /tmp/p2p10-logs
DJANGO_SETTINGS_MODULE=config.settings.prod \
CACHE_DIR=/tmp/p2p10-cache LOG_DIR=/tmp/p2p10-logs \
    uv run manage.py check --deploy
```

**Expect:** `System check identified no issues (0 silenced).` — confirmed clean against this
box's real `.env` while writing this walkthrough (2026-09-17). The `CACHE_DIR`/`LOG_DIR`
overrides point the check's `FileBasedCache` directory and rotating log handlers at scratch
temp dirs instead of creating a real `cache/`/`logs/` directory inside the repo checkout — the
same reason `config/tests/test_security_settings.py::test_deploy_check_clean` does the same
thing with `tmp_path`. `rm -rf /tmp/p2p10-cache /tmp/p2p10-logs` afterward.

This is Definition-of-Done item 2 ("`manage.py check --deploy` under prod settings: zero
warnings"), not one of the numbered 14, but it's the cheapest possible confirmation and worth
running before anything else here.

### Scenario A2 — Check 11: regular user denied at `/admin/`

1. Log in as `alice` (a regular, non-staff user) on the ordinary dev-test server
   (`uv run manage.py runserver 0.0.0.0:8000`, same as tasks 08/09/12 — no prod settings needed,
   admin permission checks aren't gated by `DEBUG`).
2. Visit `http://fedora-headless.scorpion-tench.ts.net:8000/admin/`.
3. **Expect:** bounced to the admin login page / a 302 away from the index — never the "PlanToPlate
   administration" dashboard. This is the same check task 09's walkthrough Scenario 1.2 already
   covers; if you ran that walkthrough recently you've effectively already done this one.

### Scenario A3 — Check 12: another user's private recipe is 404, not 403

1. As `hamon`, open any private recipe (most of the ~41 seeded recipes are private) and note its
   URL, e.g. `/recipes/<id>/`. Also note the equivalent API URL, `/api/recipes/<id>/`.
2. Log out, log in as `alice` (who owns nothing and has no share/public access to that recipe).
3. Request the same `/recipes/<id>/` URL. **Expect:** `404`, not `403` and not a redirect to a
   login page (`alice` *is* authenticated — this must read as "does not exist," not "exists but
   forbidden").
4. Request `/api/recipes/<id>/` (DRF browsable API, or `curl -b <alice's session cookie>
   http://…/api/recipes/<id>/`). **Expect:** `404` there too — both surfaces, same posture.

### Scenario A4 — Check 13: the login throttle returns 429

On the ordinary dev-test server (no prod settings needed — `accounts/throttling.py`'s throttle
scope has no `DEBUG` gate, and dev's `LocMemCache` is fine for a single `runserver` process):

1. POST five wrong-password login attempts in a row for the same account (the login form, or
   `curl -X POST -d "username=hamon&password=wrong"` against `/accounts/login/`, repeated five
   times — include a CSRF token dance if you're scripting it, or just use the browser form and
   submit wrong credentials five times quickly).
2. A sixth attempt within the same window. **Expect:** `429`, not another normal login-failure
   page. The page or response should carry a `Retry-After` value.
3. Wait out the window (or use a fresh account) before continuing with the rest of the
   walkthrough — you don't want the real `hamon` account's login throttled while you're trying to
   use it for other scenarios.

### Scenario A5 — Check 14: session cookie attributes

Two of the three attributes (`HttpOnly`, `SameSite=Lax`) are set in `config/settings/base.py`
and are therefore **already active on the ordinary dev-test server** — no prod settings needed:

1. Log in as `hamon` on the normal dev-test server. Open devtools → Application (or Storage) →
   Cookies → the site's cookies.
2. **Expect:** the `sessionid` cookie shows `HttpOnly` checked and `SameSite=Lax`.

The third attribute, `Secure`, is **prod-only** (`SESSION_COOKIE_SECURE = True` lives in
`config/settings/prod.py`, not `base.py` — dev deliberately leaves it off, since dev serves over
plain HTTP and a real browser silently refuses to store a `Secure` cookie from a non-HTTPS
origin at all). Confirming it therefore needs prod settings, and confirming it in a way a real
browser will actually accept needs real TLS — which is Track B territory (Scenario B3 below,
during the live rehearsal). What you *can* confirm right here, without Docker, is that Django
actually emits the header when prod settings are loaded — using `curl`, which (unlike a browser)
reports whatever `Set-Cookie` header arrives regardless of scheme:

```bash
mkdir -p /tmp/p2p10-cache /tmp/p2p10-logs
DJANGO_SETTINGS_MODULE=config.settings.prod \
CACHE_DIR=/tmp/p2p10-cache LOG_DIR=/tmp/p2p10-logs \
    uv run manage.py collectstatic --noinput
# ^ prod settings use ManifestStaticFilesStorage; every page 500s without this, since the
#   staticfiles manifest doesn't exist yet. Safe — it only populates the gitignored
#   staticfiles/ directory. `rm -rf staticfiles/` afterward if you want it gone.

DJANGO_SETTINGS_MODULE=config.settings.prod \
CACHE_DIR=/tmp/p2p10-cache LOG_DIR=/tmp/p2p10-logs \
    uv run manage.py runserver 127.0.0.1:8091 &

curl -s -D - -o /dev/null -H "X-Forwarded-Proto: https" http://127.0.0.1:8091/accounts/login/ \
    | grep -i "set-cookie\|strict-transport"
```

**Expect** a `Set-Cookie: csrftoken=...; SameSite=Lax; Secure` line and a
`Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` header. The
`X-Forwarded-Proto: https` header is what stops `SECURE_SSL_REDIRECT` from 301-looping the
request to a real HTTPS listener that doesn't exist here — `config/settings/prod.py`'s
`SECURE_PROXY_SSL_HEADER` trusts that header the same way it would trust Caddy's own. This is
the `csrftoken` cookie rather than `sessionid` (no session exists yet on a bare `GET` with no
login), but both cookies are gated by the identical `*_COOKIE_SECURE` pattern
(`CSRF_COOKIE_SECURE` / `SESSION_COOKIE_SECURE`, both `True` in the same file) — seeing one
confirms the setting is loaded and Django's cookie-emission code path honors it. Kill the
background server (`kill %1`) and clean up the scratch dirs when done.

**Result while writing this walkthrough:** ran exactly the above on 2026-09-17 — ✅ both headers
present as expected.

### Scenario A6 — Checks 7–9: backups, for real, against this box's live dataset

`make` isn't installed, so run the two Makefile targets' exact underlying commands directly (the
same substitution 10.13's resolution note describes doing in the implementation sandbox). This
is **safe against the live `db.sqlite3`**: `deploy/backup.sh` only *reads* the source database
through SQLite's Online Backup API — it never writes to it — so this is not the kind of
script-testing CLAUDE.md asks you to redirect to a scratch copy; it's the same operation
production is supposed to run against its own live database on a schedule.

```bash
cd ~/git/PlanToPlate   # this checkout

# make backup:
DJANGO_SETTINGS_MODULE=config.settings.dev \
DB_PATH=$(pwd)/db.sqlite3 BACKUP_DIR=$(pwd)/backups APP_DIR=$(pwd) \
    uv run deploy/backup.sh --skip-offbox-sync

# make restore-test (depends on the backup above already existing):
DJANGO_SETTINGS_MODULE=config.settings.dev \
DB_PATH=$(pwd)/db.sqlite3 BACKUP_DIR=$(pwd)/backups APP_DIR=$(pwd) \
    uv run deploy/restore-test.sh
```

1. **Check 7** — the backup step logs the hourly/daily/weekly `.sqlite3.gz` files and the
   `dumpdata` JSON export it wrote, each with a `.sha256` sidecar. Confirm they exist under
   `backups/` and spot-check one: `sha256sum -c backups/hourly/<file>.sha256`.
2. **Check 8** — the restore-test step's output ends with `RESULT PASS` (or fails loudly with the
   mismatched table named) after restoring into its own scratch directory, running `manage.py
   migrate` against the restored copy, and comparing every table's row count against the live
   `db.sqlite3`. This *is* "perform a real restore and confirm your recipes are there," just
   verified by row count rather than opening a browser against the restored copy — the same
   substitution 10.13's own resolution note used, and adequate here since `runserver`-ing a
   second instance against the scratch copy adds nothing the row-count comparison doesn't
   already prove.
3. **Check 9** — retention pruning is exercised by `deploy/tests/test_backup.py
   ::test_retention_prunes_correctly` against synthetic dated fixtures (`uv run pytest
   deploy/tests/test_backup.py -k retention`); a single real run here is too recent for any
   tier's window to have anything to prune, so this one stays test-covered rather than
   freshly hand-verified — noted, not a gap you need to close by hand.
4. Clean up afterward: `rm -rf backups/` — it's gitignored and was created fresh by this
   scenario.

---

## Track B — needs a Docker host

Everything below assumes you've picked a target per "Choosing a Docker target" above and have a
shell on it with Docker and Compose working (`docker compose version` succeeds).

### Scenario B1 — Clean-volume first deployment

> **Tailscale name as `SITE_ADDRESS`?** Enable HTTPS Certificates in the Tailscale admin console and add `-f compose.tailscale.yaml` to every `docker compose` command below (see `docs/OPERATIONS.md`). On a SELinux host the base file already carries the `:z` relabel.

Follow `docs/OPERATIONS.md`'s "Production first deployment" sequence literally, on the fresh
clone:

```bash
git clone <this repository> plantoplate-rehearsal
cd plantoplate-rehearsal
cp .env.example .env
make secret        # if `make` exists there; otherwise the one-liner in the Makefile's
                    # `secret:` target body works standalone via `uv run python -c "..."`
# paste the generated SECRET_KEY into .env

# .env: set real values for *this* target, not fedora-headless's:
#   ALLOWED_HOSTS=<this box's hostname or tailnet name>
#   SITE_ADDRESS=<same>
#   (CSRF_TRUSTED_ORIGINS stays unset for a single-hostname target — see OPERATIONS.md)

GIT_SHA=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
    docker compose -f compose.prod.yaml build
docker compose -f compose.prod.yaml up -d
```

**Expect (check 1):** `docker compose -f compose.prod.yaml ps` shows both `app` and `caddy` as
`healthy` within the health check's `start_period` + a few retries. Retrieve the admin temp
password before it scrolls out of the log window:

```bash
docker compose -f compose.prod.yaml logs app | grep -A2 "Temporary password"
```

Open `https://<target-host>/` in a browser. The internal-CA cert will show as untrusted (expected
for `SITE_ADDRESS=localhost` or a Tailscale name per `README.md`'s TLS section — click through
the warning, or `curl -k` for command-line checks). Log in as `admin`, complete the forced
password change, confirm `curl -k https://<target-host>/healthz/` reports
`{"status": "ok", "database": "ok"}`.

### Scenario B2 — Check 2: `DEBUG` is `False` in the running container, not just the file

```bash
docker compose -f compose.prod.yaml exec app python -c \
    "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod'); django.setup(); from django.conf import settings; print(settings.DEBUG)"
```

**Expect:** `False`. Also visit a URL guaranteed to 404 (e.g. `/this-does-not-exist/`) in the
browser — **expect Django's plain production 404 page, never the yellow debug traceback page**.
A debug traceback here would mean `DEBUG=True` leaked into the running container regardless of
what `.env` says.

### Scenario B3 — Check 14 (the part Track A couldn't finish): real browser, real TLS

Now that there's a real HTTPS listener, redo the cookie check from Scenario A5 the way a browser
actually enforces it:

1. Log in through the browser at `https://<target-host>/`.
2. Devtools → Application → Cookies. **Expect:** `sessionid` shows `Secure` ✅, `HttpOnly` ✅,
   `SameSite=Lax`. This is the confirmation Track A's `curl` trick could approximate but not
   fully deliver (a real browser actually refusing an insecure cookie is the property that
   matters).

### Scenario B4 — Check 3: static and media go through the app process, via Caddy — not around it

**Read this before checking a box next to test-plan.md's literal wording.** The design's
original topology had Caddy serving static/media directly; `tasks.md` 10.8's resolution records
an accepted deviation — static stays served by WhiteNoise in-process (`Plan/ARCHITECTURE.md`'s
tech-stack table already names WhiteNoise as the settled choice), because changing an
already-shipped, working architecture decision was judged out of scope for this task. Confirm
that instead:

1. `grep -c "file_server\|root \*" Caddyfile` from the repo → **0** — there is no Caddy directive
   that could serve a static file itself; every request, static assets included, goes through
   `reverse_proxy app:8000`.
2. In the browser (or `curl -kI https://<target-host>/static/css/reset.css`), fetch a static
   asset through the real Caddy front door. **Expect** a `200` and a long-lived
   `Cache-Control: max-age=..., public, immutable`-style header — WhiteNoise's manifest-hashed
   caching behaviour, proving the *app* served it, successfully, end to end through Caddy's
   proxy (not that Caddy served it directly, which nothing in this codebase's accepted
   architecture claims).
3. Record it as: "check 3 passes under the accepted WhiteNoise-in-process deviation, not under
   its literal original wording" rather than silently marking it done — this is exactly the kind
   of thing that should be one line in the handoff, not a silent pass.

### Scenario B5 — Check 4: restart survival

This is a throwaway target, so do the real thing:

```bash
sudo reboot
# wait for the box to come back, then:
docker compose -f compose.prod.yaml ps
curl -k https://<target-host>/healthz/
```

**Expect:** both containers back up automatically (`restart: unless-stopped` plus Docker's own
enable-on-boot systemd unit, which the package manager sets up by default), `/healthz/` reports
`"database": "ok"`, and logging in as the admin account you set up in B1 still works — the named
volumes (`plantoplate_data`, `caddy_data`, etc.) survived the reboot untouched.

### Scenario B6 — Check 5: zero CSP violations, browsing every page

With devtools' console open, click through every major page and action (recipes, dishes, meal
planner, lists, admin, the dashboard) as both a regular user and the admin. **Expect:** zero CSP
violation messages in the console, at any point. Pay particular attention to the admin pages
using select2 autocomplete (`Ingredient`, `Recipe`, `Dish`, `MealPlanProfile` add/change forms) —
this is the one part of check 5 that *was* exercised without a browser during implementation
(see `docs/OPERATIONS.md`'s 10.17 results section, "PASS, with one honest gap") specifically
because select2's JS was inspected statically rather than run in a real DOM. This scenario is
what finally closes that gap for real.

### Scenario B7 — Check 6: `securityheaders.com` — and why it likely can't give a real grade here

`securityheaders.com` fetches your site from the public internet. If your rehearsal target is
Tailscale-only or has an internal-CA cert (i.e. `SITE_ADDRESS=localhost` or a `.ts.net` name —
the deployment shape this app is actually designed for per `design.md`), the tool **cannot reach
it at all** — there is nothing to grade. This is the exact case design.md's own check 6 hedges
for ("or the reason it does not [get an A grade] is understood and documented"). Do this instead:

1. If you happen to have a real, publicly resolvable domain you're willing to point `SITE_ADDRESS`
   at temporarily (and DNS + ports 80/443 reachable from the internet), do the real check —
   Caddy will provision a real Let's Encrypt cert automatically, and `securityheaders.com` should
   return an A given `SECURE_HSTS_*`/CSP/`X-Content-Type-Options`/`Referrer-Policy` are all
   already `check --deploy`-clean.
2. Otherwise, do the manual equivalent: `curl -kI https://<target-host>/` and confirm, by hand,
   every header `securityheaders.com` grades is present and correctly valued —
   `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options: nosniff`,
   `X-Frame-Options: DENY` (or the CSP `frame-ancestors 'none'` equivalent), `Referrer-Policy`.
   Document that the grade itself is unobtainable for a Tailscale-only deployment, not that it
   was skipped.

### Scenario B8 — The two carried-forward items this rehearsal specifically owes

**From `tasks.md` 10.17's rework note — resource limits actually apply.**
`compose.prod.yaml`'s `deploy.resources.limits`/`reservations` were reviewed by inspection but
never confirmed live (no Docker in the implementation sandbox). Now that there's a real
container:

```bash
docker inspect $(docker compose -f compose.prod.yaml ps -q app) \
    --format 'Memory={{.HostConfig.Memory}} MemoryReservation={{.HostConfig.MemoryReservation}} NanoCpus={{.HostConfig.NanoCpus}}'
```

**Expect:** `Memory=805306368` (768MB), `MemoryReservation=268435456` (256MB),
`NanoCpus=2000000000` (2.0 CPUs) — confirming plain `docker compose up` (non-swarm) actually
translates the `deploy:` block into real cgroup limits on modern Compose V2, closing the gap
10.17's rework note flagged. Repeat for the `caddy` service (`cpus: "1.0"`, `memory: 256M`, no
reservation set).

**From `tasks.md` 10.8's deferred finding — live X-Forwarded-For behaviour, not just structure.**
The Caddyfile's `header_up X-Forwarded-For {remote_host}` line was only ever checked
structurally (`config/tests/test_caddyfile.py`). Confirm the actual runtime behaviour — that
Caddy really does overwrite a client-supplied header rather than trusting it:

```bash
curl -sk -H "X-Forwarded-For: 6.6.6.6" https://<target-host>/healthz/
docker compose -f compose.prod.yaml logs app --tail 5
```

**Expect (corrected 2026-11-01):** the gunicorn access log is **not** evidence here: it records
the socket peer, which is Caddy's own container address for every request, spoofed or not. Test
the behaviour that matters instead: send six wrong-password logins, each with a different
spoofed `X-Forwarded-For`. If Caddy overwrites the header they share one throttle bucket and the
sixth gets `429` with `Retry-After`; if the spoof were trusted none would be throttled. Result
on the live rehearsal: attempts 1–5 got the normal failure page, 6 and 7 got `429`.

---

### Scenario B9 — Check 10: the off-box copy actually lands off-box

`deploy/backup.sh`'s off-box step is unit-tested with a stubbed command but was never run against
a real remote. Pick whichever is easiest to stand up:

- **`rclone`**, if you already have a configured remote (cloud storage you use for anything
  else): set `RCLONE_REMOTE=<your-remote>:plantoplate-rehearsal-backups` in `.env`.
- **`rsync` over Tailscale SSH** to another box on the tailnet (e.g. back to `fedora-headless`,
  which is always on) — this needs one-time SSH key setup between the rehearsal target and the
  destination (not currently in place between any of this tailnet's boxes, per the
  dev-test-topology memory), so budget a few minutes for `ssh-copy-id` before this will work.
  Set `RSYNC_TARGET=<user>@<destination-host>:/some/backup/path/`.

```bash
docker compose -f compose.prod.yaml exec -T app deploy/backup.sh
```

**Expect:** the backup log's off-box line says it synced (not "off-box sync unconfigured —
skipping"), and — the actual proof — the file shows up with a matching checksum **on the other
machine**, not just in the log line claiming it did:

```bash
ssh <destination-host> 'ls -la /some/backup/path/hourly/ && sha256sum -c /some/backup/path/hourly/<file>.sha256'
```

---

## What matters most

- **Checks 1–6 and 10 were the honest, disclosed gap in this task's Definition of Done** — this
  walkthrough exists specifically to close it on real hardware, not to re-confirm what the
  automated suite (and the test-client-based checks 11–14) already covers well.
- **Check 3 does not literally hold** against test-plan.md's wording — WhiteNoise, not Caddy,
  serves static/media, by an accepted, already-settled architecture decision. Confirm the
  accepted version (served correctly, end to end, through Caddy's proxy) and say so explicitly
  rather than silently ticking the literal box.
- **Check 6 (`securityheaders.com`) likely cannot produce a real grade** for a Tailscale-only /
  internal-CA deployment — document *why*, per design.md's own hedge, rather than leaving it
  looking skipped.
- **A backup that has never been restored is a hypothesis** — Track A's Scenario A6 is not
  optional garnish; it's the one line in test-plan.md's manual section explicitly called "the
  one that matters."
- **Do not let Track B touch the dev-test dataset** — clean volume, fresh clone, separate
  directory or separate host. The entire value of checks 1 and 4 is proving first boot works on
  nothing, the way a real new deployment would.
