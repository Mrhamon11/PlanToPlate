# 10 — Security Hardening & Deployment · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Make the app safe to expose and safe to lose. Security review of everything built so far,
production deployment, and — the part most personal projects skip until the day it matters —
**backups that have actually been restored at least once**.

**Depends on:** 09. This is the last MVP task.

## Security review pass

A systematic audit of tasks 01–09 rather than new features. The findings become fixes.

### Object-level authorization sweep

The highest-value hour in this task. For **every** registered viewset and template view:

1. Does `get_queryset()` route through `.visible_to(user)`?
2. Is there an object-level permission on writes?
3. Do nested serializers filter their children?
4. Does a private object return 404 rather than 403?

Task 03's `test_conventions.py` automates most of this. This pass verifies the automation
still covers every model added since, and extends it where it does not.

### Input validation sweep

Every endpoint accepting user input: field-level validators present, length caps on all text
fields (an unbounded `TextField` is a cheap denial-of-service), `Decimal` bounds on quantities,
and no unvalidated `JSONField` writes.

### Dependency audit

`uv run pip-audit` (or `uv audit`) against the lockfile, wired into the Makefile so it is
repeatable rather than a one-off.

## Security headers and settings

Verified by `manage.py check --deploy` returning zero warnings, plus explicit tests.

```python
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

### Content Security Policy

Via `django-csp`. Achievable strictly because task 02 vendored every asset and banned CDNs:

```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data:;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
```

No `unsafe-inline`. Any inline handler found during this task is refactored out rather than
excused — a CSP with `unsafe-inline` in the script directive provides very little.

## Rate limiting

Task 01 throttled login. Extend to: password change (5/min), admin actions (30/min), the
import endpoint (5/hour), and a global authenticated default (1000/hour) that is generous for
20 humans and a hard ceiling for a script.

## Deployment

### Topology

```
Internet / Tailscale
        ↓
     Caddy          — TLS termination, HTTP/2, static and media, security headers
        ↓
   Gunicorn         — 2 workers × 4 gthread threads
        ↓
    Django  →  SQLite (WAL)  on a persistent volume
```

**Threads, not processes**, per `MILESTONES.md` §2 — SQLite serialises writes, and many
processes contending for the write lock is how `database is locked` appears in production.

### Caddy

Automatic TLS via Let's Encrypt for a public host, or the internal CA for a Tailscale hostname.
Static and media served directly. Health check pointed at `/healthz/` from task 00.

### Two documented paths

1. **Docker Compose** (recommended) — `compose.yaml` from task 00, extended with restart
   policies, resource limits, and log rotation.
2. **systemd** — unit files for gunicorn and Caddy for a bare VPS, since not everyone wants
   Docker on a small box.

### Cloud portability

The requirement was that this could move to EC2 or a VPS. Concretely that means: no localhost
assumptions, all config from environment variables, `DATABASE_URL` switchable to Postgres, and
`MEDIA_ROOT` behind a `django-storages` seam (task N1). Documented as a runbook, not just
claimed.

## Backups — the part that actually matters

`MILESTONES.md` C12. A recipe database with no backup story is one dead disk away from gone,
and this is a database of things people wrote by hand over years.

### Strategy

```bash
sqlite3 db.sqlite3 ".backup /backups/plantoplate-$(date +%F-%H%M).sqlite3"
```

`.backup` is the **only** correct way to copy a live SQLite database. `cp` on a WAL database
can capture a torn state — the backup appears to work and fails when you need it.

- Hourly for 24 hours, daily for 30 days, weekly for a year. Pruned by the script.
- Each backup gzipped and checksummed.
- Plus a nightly `manage.py dumpdata` JSON export — engine-independent insurance that survives
  a SQLite version problem and doubles as the Postgres migration path.
- `MEDIA_ROOT` synced separately (task N1).
- Off-box copy via `rclone` or `rsync`. A backup on the same disk as the database is not a
  backup.

### Restore drill

**A backup that has never been restored is a hypothesis.** This task includes performing a
real restore into a scratch directory and verifying object counts match. It is a Definition of
Done item, not a suggestion.

`make restore-test` automates it so it can be repeated.

## Logging and monitoring

- Structured logging to file with rotation; request logs via Caddy.
- `ERROR` and above to a separate file.
- Never log passwords, session keys, or full request bodies on auth endpoints.
- Sentry optional, off by default, DSN from env — a home server with no error reporting is
  fine, but the seam should exist.
- `/healthz/` for uptime monitoring.

## Operations runbook

`docs/OPERATIONS.md`: first deployment, updating, restore, adding a user, rotating
`SECRET_KEY`, migrating to Postgres, moving to a VPS, and what to do when SQLite says
`database is locked`.

## Edge cases

- Rotating `SECRET_KEY` invalidates every session — documented, with the expectation that
  everyone re-logs in.
- Clock skew breaking TLS: noted in the runbook.
- Disk full → SQLite corruption risk: monitor free space; the dashboard from task 09 shows it.
- WAL growing unboundedly under a long read: periodic `wal_checkpoint(TRUNCATE)`.
- Restoring into a newer schema: restore, then `migrate`. Documented in that order.

## Security notes

The final review checks specifically for the risks in `MILESTONES.md` §6:

1. IDOR — the automated convention tests plus a manual sweep.
2. Relation leaks — every nested serializer.
3. Upload handling — deferred to N1, which must not ship without it.
4. SSRF — deferred to N2, same condition.
5. Brute force — throttles verified live.
6. Import — caps verified.
7. Temp passwords — expiry and single-use verified.

Also: `DEBUG=False` verified in the running container (not merely in the file), the admin
reachable only over HTTPS, and `ALLOWED_HOSTS` genuinely restrictive.
