"""Shared fixtures for the catalog test suite.

The unit fixtures below carry the *same* ``to_base_factor`` values as
``catalog/fixtures/units.json``, so a conversion asserted here behaves identically to one the
seeded catalog would perform.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from catalog.models import Dimension, Ingredient, Tag, Unit
from core.models import Visibility

#: ``(plural, abbrev, dimension, to_base_factor, count_family)`` — the same values
#: ``catalog/fixtures/units.json`` carries, so a conversion asserted here matches the seeded
#: catalog. ``count_family`` is empty for MASS/VOLUME and set for COUNT (design.md, D34).
_UNIT_SPECS = {
    "milligram": ("milligrams", "mg", Dimension.MASS, "0.001", ""),
    "gram": ("grams", "g", Dimension.MASS, "1", ""),
    "kilogram": ("kilograms", "kg", Dimension.MASS, "1000", ""),
    "ounce": ("ounces", "oz", Dimension.MASS, "28.349523125", ""),
    "pound": ("pounds", "lb", Dimension.MASS, "453.59237", ""),
    "millilitre": ("millilitres", "ml", Dimension.VOLUME, "1", ""),
    "litre": ("litres", "l", Dimension.VOLUME, "1000", ""),
    "teaspoon": ("teaspoons", "tsp", Dimension.VOLUME, "4.9289215938", ""),
    "tablespoon": ("tablespoons", "tbsp", Dimension.VOLUME, "14.7867647814", ""),
    "cup": ("cups", "cup", Dimension.VOLUME, "236.5882365", ""),
    "each": ("each", "ea", Dimension.COUNT, "1", "generic"),
    "dozen": ("dozen", "dz", Dimension.COUNT, "12", "generic"),
    "half dozen": ("half dozen", "½ dz", Dimension.COUNT, "6", "generic"),
    "clove": ("cloves", "clove", Dimension.COUNT, "1", "clove"),
    "can": ("cans", "can", Dimension.COUNT, "1", "can"),
    "slice": ("slices", "slice", Dimension.COUNT, "1", "slice"),
}


@pytest.fixture
def make_unit(db):
    def _make(name: str) -> Unit:
        plural, abbrev, dimension, factor, count_family = _UNIT_SPECS[name]
        unit, _ = Unit.objects.get_or_create(
            name=name,
            defaults={
                "plural": plural,
                "abbrev": abbrev,
                "dimension": dimension,
                "to_base_factor": Decimal(factor),
                "count_family": count_family,
            },
        )
        return unit

    return _make


@pytest.fixture
def gram(make_unit) -> Unit:
    return make_unit("gram")


@pytest.fixture
def kilogram(make_unit) -> Unit:
    return make_unit("kilogram")


@pytest.fixture
def ounce(make_unit) -> Unit:
    return make_unit("ounce")


@pytest.fixture
def pound(make_unit) -> Unit:
    return make_unit("pound")


@pytest.fixture
def milliliter(make_unit) -> Unit:
    return make_unit("millilitre")


@pytest.fixture
def liter(make_unit) -> Unit:
    return make_unit("litre")


@pytest.fixture
def teaspoon(make_unit) -> Unit:
    return make_unit("teaspoon")


@pytest.fixture
def tablespoon(make_unit) -> Unit:
    return make_unit("tablespoon")


@pytest.fixture
def cup(make_unit) -> Unit:
    return make_unit("cup")


@pytest.fixture
def each(make_unit) -> Unit:
    return make_unit("each")


@pytest.fixture
def dozen(make_unit) -> Unit:
    return make_unit("dozen")


@pytest.fixture
def half_dozen(make_unit) -> Unit:
    return make_unit("half dozen")


@pytest.fixture
def clove(make_unit) -> Unit:
    return make_unit("clove")


@pytest.fixture
def can(make_unit) -> Unit:
    return make_unit("can")


@pytest.fixture
def slice_(make_unit) -> Unit:
    return make_unit("slice")


@pytest.fixture
def make_ingredient(db, gram):
    """Build a persisted ``Ingredient``. Defaults to a system row so tests that only need
    "an ingredient" do not have to invent an owner; pass ``owner=`` for a user row.
    """

    def _make(**kwargs) -> Ingredient:
        owner = kwargs.pop("owner", None)
        defaults = {
            "name": "Test Ingredient",
            "default_unit": gram,
            "is_system": owner is None,
            "owner": owner,
        }
        # System rows are seeded PRIVATE (04.1-04.5 review, finding #11): their readability
        # comes from is_system=True in visible_to(), not the visibility field. Match that here
        # so fixture-built system rows behave like real seeded ones.
        defaults["visibility"] = Visibility.PRIVATE
        defaults.update(kwargs)
        ingredient = Ingredient(**defaults)
        ingredient.save()
        return ingredient

    return _make


@pytest.fixture
def make_tag(db):
    def _make(name: str, kind: str = Tag._meta.get_field("kind").default) -> Tag:
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"kind": kind})
        return tag

    return _make
