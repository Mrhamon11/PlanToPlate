"""``manage.py bootstrap_admin`` — create the first admin account for a fresh deployment.

See ``Plan/01-Users-And-Auth/design.md`` and ``Plan/01-Users-And-Auth/tasks.md`` (01.9).
``docker-entrypoint.sh`` runs this exactly once per deployment volume via its own on-disk
marker (MILESTONES.md decision D18) — this command's own idempotence (refusing when a usable
admin already exists) is a second, independent safety net, not a substitute for that marker: it
is what keeps a manual ``manage.py bootstrap_admin`` safe to run twice by hand, too.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, transaction

from accounts.models import User
from accounts.services import set_temp_password

DEFAULT_USERNAME = "admin"


class Command(BaseCommand):
    help = (
        "Creates the first admin account, printing its one-time temp password. Refuses "
        "politely and does nothing if a usable admin account already exists. Pass --force to "
        "take over the requested username instead — the recovery path when the only admin "
        "account has been deactivated or its temp password has expired."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--username",
            default=DEFAULT_USERNAME,
            help=f"Username for the bootstrap admin (default: {DEFAULT_USERNAME!r}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Reuse the account already holding --username instead of refusing: reactivate "
                "it, grant staff/superuser, and issue a fresh temp password. Also skips the "
                "'an admin already exists' check."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_model = get_user_model()
        username = options["username"]
        force = options["force"]

        # Any existing, *usable* superuser is a deployment that already has a way in — not just
        # one created by this command, so re-running after someone ran createsuperuser by hand
        # (README's documented workaround until this command shipped) is a no-op too.
        # is_active=True matters: a deactivated admin is not a way in, and treating it as one
        # would wedge the deployment, since the entrypoint's marker means this never re-runs
        # automatically either. Recovery from there is --force, below.
        if not force and user_model.objects.filter(is_superuser=True, is_active=True).exists():
            self.stdout.write(
                self.style.WARNING(
                    "An admin account already exists — bootstrap_admin has nothing to do. "
                    "Re-run with --force to reset the account holding --username."
                )
            )
            return

        # Validated before creating anything: an empty or invalid username would otherwise
        # persist a superuser no login form can ever reach (AuthenticationForm's username
        # field is required) or that Django Admin refuses to save without renaming first — and
        # both the idempotence check above and the entrypoint's marker would then block any
        # retry. Field.clean() runs exactly the validators configured on the model's own
        # username field (whatever they are) plus its blank check, without touching the
        # database.
        try:
            user_model._meta.get_field("username").clean(username, None)
        except ValidationError as exc:
            raise CommandError(
                f"Invalid --username {username!r}: {' '.join(exc.messages)}"
            ) from exc

        existing = user_model.objects.filter(username=username).first()
        if existing is not None and not force:
            raise CommandError(self._refusal_message(username, existing))

        if existing is None:
            self._create(user_model(username=username, is_staff=True, is_superuser=True))
        else:
            self._reset(existing)

    def _refusal_message(self, username: str, existing: User) -> str:
        """Say which case actually blocked the run.

        Reporting every clash as "taken by a non-admin account" sent an operator recovering a
        deactivated admin off to create a *second* superuser under another name — the one
        scenario the is_active check above exists to make recoverable.
        """
        if existing.is_superuser:
            held_by = (
                "a deactivated admin account" if not existing.is_active else "an admin account"
            )
        else:
            held_by = "a non-admin account"
        return (
            f"Username {username!r} is already taken by {held_by}. Re-run with --force to "
            "reactivate that account, grant it staff/superuser, and issue it a fresh temp "
            "password, or pass a different --username to leave it alone."
        )

    def _create(self, user: User) -> None:
        try:
            temp_password = set_temp_password(user)
        except IntegrityError as exc:
            # Only reachable as a race: the username was free when checked just above. Says so
            # rather than guessing at which kind of account claimed it.
            raise CommandError(
                f"Could not create admin user {user.username!r}: {exc}. That username was "
                "claimed between this command's check and its write — re-run the command to "
                "see which account now holds it."
            ) from exc
        self.stdout.write(self.style.SUCCESS(f"Created admin user {user.username!r}."))
        self._report(temp_password)

    def _reset(self, user: User) -> None:
        """--force path: make the account already holding the username a usable admin again.

        The flag grants and the temp password are one unit of work — a failure partway through
        must not leave a promoted account whose password nobody was ever shown.
        """
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        with transaction.atomic():
            user.save(update_fields=["is_active", "is_staff", "is_superuser"])
            temp_password = set_temp_password(user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Reset admin user {user.username!r} (reactivated, staff and superuser granted)."
            )
        )
        self._report(temp_password)

    def _report(self, temp_password: str) -> None:
        self.stdout.write(f"Temporary password (shown once): {temp_password}")
        self.stdout.write(
            "This password is not stored in the database and this command will not print it "
            "again. In the Docker Compose deployment, docker-entrypoint.sh runs this command "
            "with its output going to the container log, where it will remain readable via "
            "`docker compose logs app` until that log is rotated or cleared — treat it as "
            "sensitive until the admin completes the forced password change on first login."
        )
