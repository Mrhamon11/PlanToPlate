# syntax=docker/dockerfile:1
#
# Multi-stage build. The builder resolves dependencies from the committed uv.lock; the
# runtime stage copies only the built virtualenv and the app, and never sees uv, apt caches,
# or anything from the builder's filesystem. Pinning the base image by digest (not just the
# `3.13-slim-bookworm` tag) means a rebuild months from now reproduces the same image instead
# of silently picking up whatever Debian shipped that week.
FROM python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Build-time switch selecting the optional `postgres` dependency group (psycopg[binary]).
# Default "false" keeps the image SQLite-only, which is what this project is sized for and
# what every other build produces unchanged. Select the Postgres driver with:
#   docker compose build --build-arg INCLUDE_POSTGRES=true
#   docker build --build-arg INCLUDE_POSTGRES=true .
# `uv sync --frozen` never re-resolves either way — the driver version, like everything else,
# comes from the committed uv.lock.
ARG INCLUDE_POSTGRES=false

# Dependencies first, app code second — the dependency layer only invalidates when
# pyproject.toml/uv.lock change, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INCLUDE_POSTGRES" = "true" ]; then \
        uv sync --frozen --no-dev --group prod --group postgres --no-install-project; \
    else \
        uv sync --frozen --no-dev --group prod --no-install-project; \
    fi

COPY . .
# --frozen: the build fails rather than silently resolving different versions against a
# lockfile that has drifted from pyproject.toml. A build that quietly upgrades a dependency
# is not a reproducible one. `prod` brings in gunicorn; `dev` (pytest, ruff, ...) is excluded
# from the image entirely; `postgres` (psycopg[binary]) is included only when INCLUDE_POSTGRES=true.
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INCLUDE_POSTGRES" = "true" ]; then \
        uv sync --frozen --no-dev --group prod --group postgres; \
    else \
        uv sync --frozen --no-dev --group prod; \
    fi


FROM python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1 AS runtime

# Pillow's usual runtime dependencies. Installed here — the runtime stage — not just the
# builder, or the image builds fine and then fails the first time someone uploads an image.
# Pillow itself is not a dependency yet (it lands in task N1); these libraries are cheap to
# carry now and save a rebuild later.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libjpeg62-turbo \
        zlib1g \
        libwebp7 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --create-home app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app . .

# Writable at runtime: collectstatic regenerates this on every boot (ephemeral, not a named
# volume), and the data/media directories are the mount points for the named volumes that
# hold the SQLite database and uploaded images. Created and chowned here so the non-root user
# owns them before the volumes are mounted over them.
RUN mkdir -p /app/staticfiles /app/data /app/media \
    && chown -R app:app /app/staticfiles /app/data /app/media \
    && chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
