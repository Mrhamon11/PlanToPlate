"""Gunicorn configuration for the production container (10.9, design.md "Deployment" —
"Gunicorn — 2 workers x 4 gthread threads").

Loaded via ``gunicorn config.wsgi:application --config gunicorn.conf.py`` from
``docker-entrypoint.sh``, which is also where ``exec`` hands gunicorn PID 1 so it receives
``SIGTERM`` directly on ``docker compose stop`` — see that file's own comment. Threads, not more
processes: ``MILESTONES.md`` section 2 — SQLite serialises writes, and many worker *processes*
each holding their own connection is how "database is locked" shows up under real load, while
threads within few processes share the busy_timeout wait gracefully instead of piling up.
"""

bind = "0.0.0.0:8000"

workers = 2
threads = 4
worker_class = "gthread"

# gunicorn's heartbeat file for each worker defaults to a location under the system temp
# directory; on some container filesystems (overlay2 in particular) that file's mtime updates
# can be slow enough to trip gunicorn's own worker-timeout heuristic under load, killing a
# worker that was actually fine. /dev/shm is a tmpfs every Linux container has, and this file
# is a few bytes — nothing here needs it to be disk-backed or persistent.
worker_tmp_dir = "/dev/shm"  # noqa: S108 -- container-local tmpfs, not a shared host /tmp

# `timeout` is gunicorn's own silence watchdog: a gthread worker that has not reported back
# in this many seconds is killed and restarted, on the assumption it is wedged rather than
# genuinely busy. 60s comfortably outlasts SQLite's own 5s busy_timeout (config/settings/
# base.py's SQLITE_OPTIONS) plus a slow query, without leaving a truly hung worker occupying a
# thread indefinitely. `graceful_timeout` bounds how long a worker gets to finish in-flight
# requests after SIGTERM before gunicorn escalates to SIGKILL — 30s so `docker compose stop`
# (which itself waits out Compose's own stop_grace_period before SIGKILL) does not abandon a
# request mid-write to SQLite.
timeout = 60
graceful_timeout = 30

# Recycles each worker after roughly this many requests (jittered so both workers do not
# restart in the same instant and drop capacity together) — cheap insurance against a slow
# memory leak turning into an OOM kill on a deployment nobody restarts for months. A worker
# recycling mid-request is safe: gunicorn finishes the current request before tearing it down.
max_requests = 1000
max_requests_jitter = 100

# Never enable preload_app here. Preloading forks each worker from a parent that has already
# imported Django and, on first use, opened the SQLite connection in config/settings/base.py's
# DATABASES — a connection object shared across a fork is not something SQLite (or Django's
# connection handling) supports safely. Leaving this at gunicorn's own default (False) means
# each worker imports the app and opens its own connection independently, which is what
# SQLITE_OPTIONS' per-connection PRAGMAs (WAL, busy_timeout) assume in the first place.
preload_app = False

accesslog = "-"
errorlog = "-"
# gunicorn's own default combined-log format, with %(L)s (request duration in seconds)
# appended — Caddy's own access log covers the edge, but a slow request is easiest to spot
# right next to the worker that actually served it.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'
