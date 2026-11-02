.PHONY: install run test lint fmt check migrate shell secret audit docker-build docker-up docker-logs docker-build-prod docker-up-prod docker-logs-prod backup restore-test

install:
	uv sync

run:
	uv run manage.py runserver

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

check:
	uv run manage.py check

migrate:
	uv run manage.py migrate

shell:
	uv run manage.py shell

# Prints a fresh SECRET_KEY to paste into .env. Never writes .env directly — .env may
# already hold other values worth keeping, and overwriting it silently is the kind of
# surprise this Makefile should not spring on you.
#
# Deliberately not Django's own get_random_secret_key(): its charset includes `$`, and
# Docker Compose interpolates `$VAR`/`${VAR}` in .env file values (not just in compose.yaml).
# A `$` landing in SECRET_KEY is silently stripped when the container starts — a quieter,
# weaker key than the one you generated, with no error to notice. Same length and entropy,
# charset just excludes the one character that is unsafe to paste into this particular file.
secret:
	@uv run python -c "import secrets; chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#%^&*(-_=+)'; print(''.join(secrets.choice(chars) for _ in range(50)))"

# pip-audit against every dependency group in uv.lock (dev, prod, postgres) — not just what a
# default `uv sync` installs. `--with pip-audit` runs it from an ephemeral overlay so the
# scanner itself is never a project dependency (10.6, design.md "Dependency audit"); it then
# scans whatever `uv run` synced into the project venv, which the --group flags widen to
# everything the lockfile can produce, including the optional postgres driver nobody has
# opted into yet. Clean as of 2026-09-17 ("No known vulnerabilities found"); if this ever
# reports a finding, resolve it (upgrade via `uv add`/`uv lock --upgrade-package`, which needs
# permission per CLAUDE.md) or record why it is accepted, right here.
audit:
	uv run --group dev --group prod --group postgres --with pip-audit pip-audit

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-logs:
	docker compose logs -f

# compose.prod.yaml (10.7): the production stack, with resource limits, bounded log
# retention, and provenance build args compose.yaml's dev-oriented file does not carry.
# GIT_SHA/BUILD_DATE are computed fresh here rather than read from .env (10.7b) — an image
# always reports the commit it was actually built from, never a value someone forgot to
# update.
docker-build-prod:
	GIT_SHA=$$(git rev-parse --short HEAD) BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		docker compose -f compose.prod.yaml build

docker-up-prod:
	docker compose -f compose.prod.yaml up -d

docker-logs-prod:
	docker compose -f compose.prod.yaml logs -f

# deploy/backup.sh (10.11/10.12) against this checkout's own local db.sqlite3 — the bare-`uv
# run` dev convenience. Docker Compose and the systemd path schedule the same script via a
# timer instead (docs/OPERATIONS.md "Backups" — "Scheduling"); this target is for running one
# by hand, e.g. right before `make restore-test`.
backup:
	DJANGO_SETTINGS_MODULE=config.settings.dev \
	DB_PATH=$(CURDIR)/db.sqlite3 \
	BACKUP_DIR=$(CURDIR)/backups \
	APP_DIR=$(CURDIR) \
		uv run deploy/backup.sh --skip-offbox-sync

# The restore drill (10.13, design.md "Restore drill" — "A backup that has never been restored
# is a hypothesis, not a backup"). Takes a fresh backup of this checkout's db.sqlite3, restores
# it into a scratch directory, migrates it, and compares every table's row count against the
# live source — see deploy/restore-test.sh and docs/OPERATIONS.md "Restore drill". Exits
# nonzero on any mismatch, so this is safe to wire into a pre-deploy check, not just run by hand.
restore-test: backup
	DJANGO_SETTINGS_MODULE=config.settings.dev \
	DB_PATH=$(CURDIR)/db.sqlite3 \
	BACKUP_DIR=$(CURDIR)/backups \
	APP_DIR=$(CURDIR) \
		uv run deploy/restore-test.sh
