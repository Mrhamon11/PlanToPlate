.PHONY: install run test lint fmt check migrate shell secret docker-build docker-up docker-logs

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

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-logs:
	docker compose logs -f
