"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Seeding"."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.management import call_command

from catalog.models import Ingredient, Tag, Unit
from core.models import Visibility

pytestmark = pytest.mark.django_db


def _seed() -> None:
    call_command("seed_catalog", stdout=io.StringIO(), stderr=io.StringIO())


def test_seed_creates_system_objects():
    _seed()

    assert Unit.objects.exists()
    assert Tag.objects.exists()
    assert Ingredient.objects.exists()

    assert not Unit.objects.filter(is_system=False).exists()
    assert not Ingredient.objects.filter(is_system=False).exists()
    assert not Ingredient.objects.filter(owner__isnull=False).exists()


def test_seed_is_idempotent():
    _seed()
    counts = (Unit.objects.count(), Tag.objects.count(), Ingredient.objects.count())

    _seed()

    assert (Unit.objects.count(), Tag.objects.count(), Ingredient.objects.count()) == counts
    # And nothing was duplicated by case/whitespace drift.
    assert Ingredient.objects.filter(name__iexact="Olive Oil").count() == 1


def test_seed_updates_in_place_not_duplicate():
    _seed()
    salt = Ingredient.objects.get(name="Salt")
    salt.is_staple = False
    salt.save()

    _seed()

    salt.refresh_from_db()
    assert salt.is_staple is True  # the fixture value was restored, not a second row created
    assert Ingredient.objects.filter(name="Salt").count() == 1


def test_seed_does_not_touch_user_ingredients(user_factory):
    alice = user_factory(username="alice")
    seeded_name = "All-Purpose Flour"

    _seed()
    mine = Ingredient.objects.create(
        name=seeded_name,
        default_unit=Unit.objects.get(name="cup"),
        owner=alice,
        is_system=False,
        visibility=Visibility.PRIVATE,
        is_staple=True,
        notes="my pantry note",
    )

    _seed()

    mine.refresh_from_db()
    assert mine.owner == alice
    assert mine.is_system is False
    assert mine.is_staple is True
    assert mine.notes == "my pantry note"

    # The system catalog still got its own row, side by side with the user's.
    system_rows = Ingredient.objects.filter(name__iexact=seeded_name, is_system=True)
    assert system_rows.count() == 1
    assert system_rows.get().owner is None


def test_seeded_densities_present():
    _seed()

    assert Ingredient.objects.get(name="Water").density_g_per_ml == Decimal("1.0000")
    for needle in ("flour", "sugar", "oil"):
        assert Ingredient.objects.filter(
            name__icontains=needle, density_g_per_ml__isnull=False
        ).exists(), needle


def test_seeded_staples_marked():
    _seed()

    assert Ingredient.objects.get(name="Salt").is_staple is True
    assert Ingredient.objects.get(name="Black Pepper").is_staple is True
    assert Ingredient.objects.filter(name__icontains="oil", is_staple=True).exists()


def test_seeded_base_units_have_factor_one():
    _seed()

    for name in ("gram", "millilitre", "each"):
        assert Unit.objects.get(name=name).to_base_factor == Decimal("1")


def test_seeded_system_ingredients_are_not_visibility_public():
    """04.1-04.5 review, finding #11: system ingredients are readable via ``is_system=True``
    in ``visible_to``, not via their ``visibility`` field — seeding them PUBLIC made
    ``core/filters.py``'s ``?public=true`` return all ~176 built-ins alongside genuinely
    user-published rows. They are seeded PRIVATE.
    """
    _seed()

    assert (
        not Ingredient.objects.filter(is_system=True)
        .exclude(visibility=Visibility.PRIVATE)
        .exists()
    )


def test_public_filter_excludes_system_ingredients(user_factory):
    from rest_framework.test import APIClient

    _seed()
    api = APIClient()
    api.force_login(user_factory(username="carol"))

    response = api.get("/api/ingredients/?public=true")

    assert response.status_code == 200
    assert response.data["results"] == []


def test_seed_warns_on_ambiguous_unit_lookup_key(monkeypatch):
    """04.1-04.5 review, finding #7: if a fixture ever names a unit whose ``name`` collides
    with another unit's ``abbrev`` (or vice versa), the seed keeps the first binding and warns
    rather than silently letting the later row shadow the earlier in the lookup dict.
    """
    from catalog.management.commands.seed_catalog import Command

    real_load = Command._load

    def fake_load(self, name):
        if name == "units":
            return [
                {
                    "name": "widget",
                    "abbrev": "wgt",
                    "dimension": "COUNT",
                    "to_base_factor": "1",
                    "count_family": "widget",
                },
                {
                    "name": "wgt",
                    "abbrev": "wg2",
                    "dimension": "COUNT",
                    "to_base_factor": "1",
                    "count_family": "wgt",
                },
            ]
        if name in {"tags", "ingredients"}:
            return []
        return real_load(self, name)

    monkeypatch.setattr(Command, "_load", fake_load)
    stderr = io.StringIO()
    call_command("seed_catalog", stdout=io.StringIO(), stderr=stderr)

    assert "Ambiguous unit lookup key 'wgt'" in stderr.getvalue()


def test_malformed_ingredient_rows_are_skipped_not_fatal(monkeypatch):
    """A future fixture edit that names a nonexistent unit, or repeats a name, must not abort
    the whole seed mid-transaction — the row is skipped with a warning and the rest land.
    """
    from catalog.management.commands.seed_catalog import Command

    real_load = Command._load

    def fake_load(self, name):
        if name == "ingredients":
            return [
                {"name": "Good One", "unit": "g"},
                {"name": "Bad Unit", "unit": "nonexistent-unit"},
                {"name": "Good One", "unit": "g"},  # duplicate name
            ]
        return real_load(self, name)

    monkeypatch.setattr(Command, "_load", fake_load)
    stderr = io.StringIO()
    call_command("seed_catalog", stdout=io.StringIO(), stderr=stderr)

    assert Ingredient.objects.filter(name="Good One").count() == 1
    assert not Ingredient.objects.filter(name="Bad Unit").exists()
    warnings = stderr.getvalue()
    assert "nonexistent-unit" in warnings
    assert "duplicate" in warnings


def test_unknown_tag_name_warns_and_is_skipped(monkeypatch):
    """An unknown tag name is dropped with a warning — same as an unknown unit — so a fixture
    typo does not silently seed an ingredient the meal planner's tag limits never see.
    """
    from catalog.management.commands.seed_catalog import Command

    real_load = Command._load

    def fake_load(self, name):
        if name == "ingredients":
            return [{"name": "Tagged One", "unit": "g", "tags": ["chicken", "not-a-real-tag"]}]
        return real_load(self, name)

    monkeypatch.setattr(Command, "_load", fake_load)
    stderr = io.StringIO()
    call_command("seed_catalog", stdout=io.StringIO(), stderr=stderr)

    ingredient = Ingredient.objects.get(name="Tagged One")
    assert {t.name for t in ingredient.tags.all()} == {"chicken"}
    assert "not-a-real-tag" in stderr.getvalue()
