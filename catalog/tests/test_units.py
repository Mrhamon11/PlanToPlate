"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Unit model"."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError

from catalog.models import GENERIC_COUNT_FAMILY, Dimension, Unit

pytestmark = pytest.mark.django_db


def test_seeded_units_exist():
    """The base unit of each dimension is seeded and its factor to base is exactly 1."""
    call_command("seed_catalog", stdout=io.StringIO(), stderr=io.StringIO())

    for dimension, base_name in (
        (Dimension.MASS, "gram"),
        (Dimension.VOLUME, "millilitre"),
        (Dimension.COUNT, "each"),
    ):
        base = Unit.objects.get(name=base_name)
        assert base.dimension == dimension
        assert base.to_base_factor == Decimal("1")


def test_unit_name_unique(make_unit):
    make_unit("gram")

    with pytest.raises(IntegrityError):
        Unit.objects.create(
            name="gram",
            plural="grams",
            abbrev="g2",
            dimension=Dimension.MASS,
            to_base_factor=Decimal("1"),
        )


def test_unit_str_renders_abbreviation(make_unit):
    assert str(make_unit("tablespoon")) == "tbsp"


def test_unit_label_for_singular_and_plural(make_unit):
    cup = make_unit("cup")
    assert cup.label_for(Decimal("1")) == "cup"
    assert cup.label_for(Decimal("2")) == "cups"
    assert cup.label_for(Decimal("0.5")) == "cup"


def test_to_base_factor_must_be_positive(make_unit):
    with pytest.raises(IntegrityError):
        Unit.objects.create(
            name="bad",
            plural="bads",
            abbrev="bad",
            dimension=Dimension.MASS,
            to_base_factor=Decimal("0"),
        )


def test_zero_factor_rejected_by_full_clean():
    """04.1-04.5 review, finding #20: the field validator rejects it at ``full_clean()`` too,
    not only the DB ``CheckConstraint`` — so the admin form surfaces it as a field error.
    """
    unit = Unit(
        name="bad",
        plural="bads",
        abbrev="bad2",
        dimension=Dimension.MASS,
        to_base_factor=Decimal("0"),
    )
    with pytest.raises(ValidationError):
        unit.full_clean()


def test_abbrev_is_unique(make_unit):
    make_unit("gram")

    with pytest.raises(IntegrityError):
        Unit.objects.create(
            name="grahm",
            plural="grahms",
            abbrev="g",
            dimension=Dimension.MASS,
            to_base_factor=Decimal("1"),
        )


def test_is_generic_count(make_unit):
    assert make_unit("each").is_generic_count is True
    assert make_unit("dozen").is_generic_count is True
    assert make_unit("half dozen").is_generic_count is True
    assert make_unit("clove").is_generic_count is False
    assert make_unit("gram").is_generic_count is False
    assert GENERIC_COUNT_FAMILY == "generic"
