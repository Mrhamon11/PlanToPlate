"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Unit model"."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import IntegrityError

from catalog.models import Dimension, Unit

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
