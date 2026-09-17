"""``manage.py import_json <file> --owner <username>`` — the shell entry point for the bulk
JSON importer (task 09.11, ``Plan/09-Admin-Control-Center/design.md``, "Bulk JSON import").

Thin over :func:`core.services.importer.run_import`; the admin upload page calls the same
function, so the two paths cannot drift (``test_management_command_matches_admin_page``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from core.services.importer import (
    SKIP_EXISTING,
    UPDATE_EXISTING,
    ImportValidationError,
    run_import,
)


class Command(BaseCommand):
    help = (
        "Import recipes, ingredients and dishes from a JSON file. The file is fully validated "
        "before anything is written; a single fault rejects the whole import."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("file", type=str, help="Path to the JSON import file.")
        parser.add_argument(
            "--owner",
            required=True,
            help="Username that will own every imported object. The file cannot override this.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--skip-existing",
            dest="mode",
            action="store_const",
            const=SKIP_EXISTING,
            help="Leave an existing (owner, name) match untouched (the default).",
        )
        mode.add_argument(
            "--update-existing",
            dest="mode",
            action="store_const",
            const=UPDATE_EXISTING,
            help="Overwrite an existing (owner, name) match's fields and components.",
        )
        parser.set_defaults(mode=SKIP_EXISTING)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report what would be imported, writing nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"No such file: {path}")

        user_model = get_user_model()
        try:
            owner = user_model.objects.get(username=options["owner"])
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No user with username {options['owner']!r}.") from exc

        raw = path.read_bytes()
        try:
            report = run_import(
                raw=raw,
                owner=owner,
                actor=owner,
                mode=options["mode"],
                dry_run=options["dry_run"],
            )
        except ImportValidationError as exc:
            self.stderr.write(self.style.ERROR("Import rejected:"))
            for problem in exc.problems:
                self.stderr.write(f"  {problem}")
            raise CommandError(f"{len(exc.problems)} problem(s) — nothing was imported.") from exc

        header = "Dry run — nothing written." if report.dry_run else "Import complete."
        self.stdout.write(self.style.SUCCESS(header))
        for line in report.as_lines():
            self.stdout.write(f"  {line}")
