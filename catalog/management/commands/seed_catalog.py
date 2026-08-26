"""``manage.py seed_catalog`` — populate the shared catalog with system units, tags, and
ingredients (``Plan/04-Units-And-Ingredients/design.md``, "Seed data").

Idempotent by design: every row is matched on its natural key (``name``, and additionally
``is_system=True`` for ingredients) and updated in place rather than duplicated, so the command
is safe to re-run after the fixtures grow. It never reads or writes a user-owned ingredient —
the ``is_system=True`` filter is what keeps a user's own "Flour" untouched when the catalog
seeds its own.

``docker-entrypoint.sh`` runs this once per deployment volume via an on-disk marker
(MILESTONES.md decision D18); running it again by hand is harmless.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Ingredient, Tag, Unit
from core.models import Visibility

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


class Command(BaseCommand):
    help = "Seed system units, tags, and ingredients. Idempotent; never touches user data."

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic():
            units = self._seed_units()
            tags = self._seed_tags()
            ing_created, ing_updated = self._seed_ingredients(units, tags)

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog seeded: {len(units)} units, {len(tags)} tags, "
                f"{ing_created} ingredients created, {ing_updated} updated."
            )
        )

    def _load(self, name: str) -> list[dict[str, Any]]:
        with (FIXTURE_DIR / f"{name}.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def _seed_units(self) -> dict[str, Unit]:
        lookup: dict[str, Unit] = {}
        for row in self._load("units"):
            unit, _ = Unit.objects.update_or_create(
                name=row["name"],
                defaults={
                    "plural": row.get("plural", ""),
                    "abbrev": row["abbrev"],
                    "dimension": row["dimension"],
                    "to_base_factor": Decimal(str(row["to_base_factor"])),
                    "count_family": row.get("count_family", ""),
                    "is_system": True,
                },
            )
            lookup[unit.name.lower()] = unit
            lookup[unit.abbrev.lower()] = unit
        return lookup

    def _seed_tags(self) -> dict[str, Tag]:
        lookup: dict[str, Tag] = {}
        for row in self._load("tags"):
            tag, _ = Tag.objects.update_or_create(
                name=row["name"],
                defaults={"kind": row["kind"]},
            )
            lookup[tag.name.lower()] = tag
        return lookup

    def _seed_ingredients(self, units: dict[str, Unit], tags: dict[str, Tag]) -> tuple[int, int]:
        created = 0
        updated = 0
        seen: set[str] = set()
        for row in self._load("ingredients"):
            name = row["name"].strip()
            key = name.lower()
            if key in seen:
                self.stderr.write(f"Skipping duplicate ingredient in fixture: {name!r}")
                continue
            seen.add(key)

            unit = units.get(row["unit"].lower())
            if unit is None:
                self.stderr.write(f"Skipping {name!r}: unknown unit {row['unit']!r}")
                continue

            density = row.get("density_g_per_ml")
            fields = {
                "default_unit": unit,
                "density_g_per_ml": Decimal(str(density)) if density is not None else None,
                "is_staple": bool(row.get("staple", False)),
                "visibility": Visibility.PUBLIC,
            }

            # Match on is_system=True only: a user's own ingredient sharing this name is not
            # ours to read or modify.
            ingredient = Ingredient.objects.filter(is_system=True, name__iexact=name).first()
            if ingredient is None:
                ingredient = Ingredient(name=name, owner=None, is_system=True, **fields)
                ingredient.save()
                created += 1
            else:
                ingredient.name = name
                for attr, value in fields.items():
                    setattr(ingredient, attr, value)
                ingredient.save()
                updated += 1

            resolved_tags = []
            for tag_name in row.get("tags", []):
                tag = tags.get(tag_name.lower())
                if tag is None:
                    self.stderr.write(f"Skipping {name!r} tag {tag_name!r}: unknown tag")
                    continue
                resolved_tags.append(tag)
            ingredient.tags.set(resolved_tags)

        return created, updated
