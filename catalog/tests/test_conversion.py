"""``Plan/04-Units-And-Ingredients/test-plan.md`` — "Conversion", the correctness core.

Every assertion here is about the service in ``catalog/services/units.py`` doing exact
``Decimal`` arithmetic and refusing — loudly, by name — any conversion it cannot perform
without inventing a density.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from catalog.exceptions import IncompatibleUnits
from catalog.services.units import convert, humanize, to_base

pytestmark = pytest.mark.django_db


class _FakeIngredient:
    """Stand-in for anything the service reads a density off — the service only touches
    ``density_g_per_ml``."""

    def __init__(self, density: Decimal | None) -> None:
        self.density_g_per_ml = density


def test_convert_within_mass(gram, kilogram, pound):
    assert convert(Decimal("1"), kilogram, gram) == Decimal("1000")
    assert round(convert(Decimal("1"), pound, gram), 3) == Decimal("453.592")


def test_convert_within_volume(milliliter, teaspoon, tablespoon, cup):
    assert round(convert(Decimal("1"), cup, milliliter), 3) == Decimal("236.588")
    assert convert(Decimal("1"), tablespoon, teaspoon) == Decimal("3")


def test_convert_same_unit_is_identity(cup):
    original = Decimal("2.5")
    result = convert(original, cup, cup)
    assert result == original
    # Untouched by factor arithmetic: not re-quantised, not multiplied through and back.
    assert result is original


def test_convert_round_trip(gram, ounce):
    grams = Decimal("100")
    there = convert(grams, gram, ounce)
    back = convert(there, ounce, gram)
    assert abs(back - grams) < Decimal("0.0001")


def test_mass_to_volume_with_density(gram, milliliter):
    water = _FakeIngredient(Decimal("1.0"))
    assert convert(Decimal("100"), gram, milliliter, ingredient=water) == Decimal("100")


def test_mass_to_volume_without_density_raises(gram, milliliter):
    with pytest.raises(IncompatibleUnits) as exc:
        convert(Decimal("100"), gram, milliliter)
    assert "density" in str(exc.value)
    assert exc.value.from_unit == gram
    assert exc.value.to_unit == milliliter


def test_mass_to_volume_with_null_density_raises(gram, milliliter):
    no_density = _FakeIngredient(None)
    with pytest.raises(IncompatibleUnits):
        convert(Decimal("100"), gram, milliliter, ingredient=no_density)


def test_count_to_mass_always_raises(each, gram):
    """COUNT ↔ MASS is refused even with a density set, and the exception names both units and
    gives the count-specific reason — held to the same standard as its mass↔volume sibling so
    it cannot pass on an unrelated ``IncompatibleUnits``.
    """
    dense = _FakeIngredient(Decimal("1.0"))

    with pytest.raises(IncompatibleUnits) as exc:
        convert(Decimal("3"), each, gram, ingredient=dense)
    assert exc.value.from_unit == each
    assert exc.value.to_unit == gram
    assert "ingredient-specific weight" in str(exc.value)

    with pytest.raises(IncompatibleUnits) as exc:
        convert(Decimal("150"), gram, each, ingredient=dense)
    assert exc.value.from_unit == gram
    assert exc.value.to_unit == each
    assert "ingredient-specific weight" in str(exc.value)


def test_convert_within_generic_count_family(each, dozen, half_dozen):
    """``each``/``dozen``/``half dozen`` share one family and interconvert on 1/6/12."""
    assert convert(Decimal("2"), dozen, each) == Decimal("24")
    assert convert(Decimal("1"), dozen, each) == Decimal("12")
    assert convert(Decimal("1"), dozen, half_dozen) == Decimal("2")
    assert convert(Decimal("3"), half_dozen, each) == Decimal("18")
    # The sub-1 direction too (04.1-04.5 review, finding #22): 6 each is exactly half a dozen.
    assert convert(Decimal("6"), each, dozen) == Decimal("0.5")
    assert convert(Decimal("3"), each, half_dozen) == Decimal("0.5")


def test_convert_between_unrelated_count_units_raises(clove, can):
    """All discrete piece units once shared ``to_base_factor == 1``, so this returned ``2``.
    "1 can" and "2 cloves" have no fixed ratio — the service must refuse (D34).
    """
    with pytest.raises(IncompatibleUnits) as exc:
        convert(Decimal("2"), clove, can)
    assert exc.value.from_unit == clove
    assert exc.value.to_unit == can
    assert "clove" in str(exc.value) and "can" in str(exc.value)
    assert "no fixed ratio" in str(exc.value)


def test_convert_piece_unit_to_generic_count_raises(slice_, dozen):
    with pytest.raises(IncompatibleUnits) as exc:
        convert(Decimal("1"), slice_, dozen)
    assert exc.value.from_unit == slice_
    assert exc.value.to_unit == dozen
    assert "no fixed ratio" in str(exc.value)


def test_same_unit_short_circuits_before_count_family_logic(clove):
    """A singleton counted unit converting *to itself* is the identity short-circuit
    (``_same_unit``), which runs before ``_same_count_family`` is ever consulted — so a
    piece unit still round-trips to itself even though it converts to nothing else
    (04.1-04.5 review, finding #21: renamed from ``..._to_itself_is_identity`` to say which
    branch it actually exercises).
    """
    assert convert(Decimal("5"), clove, clove) == Decimal("5")


def test_convert_rejects_float_quantity(gram, kilogram):
    """04.1-04.5 review, finding #13: a runtime ``float`` is refused at the service boundary,
    not silently coerced — ``Decimal(str(0.1 + 0.2))`` already carries the rounding error the
    "Decimal end to end" DoD exists to keep out.
    """
    with pytest.raises(TypeError):
        convert(0.5, kilogram, gram)  # noqa: no float in production; deliberate here
    with pytest.raises(TypeError):
        to_base(0.5, gram)


def test_seeded_units_respect_d34_count_family_contract():
    """04.1-04.5 review, finding #16: the D34 contract holds over the *seeded* Unit rows, not
    only the hand-built conftest fixtures — ``each``/``dozen``/``half dozen`` interconvert,
    a packaging unit converts only to itself, and ``clove`` -> ``can`` refuses.
    """
    from django.core.management import call_command

    from catalog.models import GENERIC_COUNT_FAMILY, Unit

    call_command("seed_catalog", stdout=io.StringIO(), stderr=io.StringIO())

    each = Unit.objects.get(name="each")
    dozen = Unit.objects.get(name="dozen")
    half_dozen = Unit.objects.get(name="half dozen")
    clove = Unit.objects.get(name="clove")
    can = Unit.objects.get(name="can")

    families = {each.count_family, dozen.count_family, half_dozen.count_family}
    assert families == {GENERIC_COUNT_FAMILY}
    assert convert(Decimal("1"), dozen, each) == Decimal("12")
    assert convert(Decimal("2"), half_dozen, each) == Decimal("12")

    assert convert(Decimal("3"), clove, clove) == Decimal("3")
    with pytest.raises(IncompatibleUnits):
        convert(Decimal("2"), clove, can)


def test_convert_uses_decimal_not_float(liter, milliliter, gram, kilogram):
    result = convert(Decimal("0.3"), liter, milliliter)
    assert isinstance(result, Decimal)
    # 0.1 + 0.2 is the canonical binary-float failure; through the service it stays exact.
    a = convert(Decimal("0.1"), liter, milliliter)
    b = convert(Decimal("0.2"), liter, milliliter)
    assert a + b == Decimal("300")

    # The load-bearing guard: 1.234...e8 kg → g needs 18 significant digits, more than a
    # binary ``float`` carries (~15), so a float implementation lands on ...456790 here and
    # fails — end-quantisation to 1e-6 cannot rescue precision already lost before it runs.
    assert convert(Decimal("123456789.123456789"), kilogram, gram) == Decimal("123456789123.456789")


def test_convert_precision_preserved(cup, milliliter):
    third_cup = Decimal("0.333333")
    there = convert(third_cup, cup, milliliter)
    back = convert(there, milliliter, cup)
    assert abs(back - third_cup) < Decimal("0.00001")


def test_zero_quantity(gram, kilogram):
    assert convert(Decimal("0"), kilogram, gram) == Decimal("0")


def test_to_base(gram, kilogram):
    assert to_base(Decimal("2"), kilogram) == Decimal("2000")
    assert to_base(Decimal("5"), gram) == Decimal("5")


def test_to_base_is_not_quantised(teaspoon):
    """``to_base`` is an intermediate value, so it returns the raw product — quantising it
    would make ``3 * to_base(1, tsp)`` disagree with ``to_base(3, tsp)`` at the 6th decimal.
    """
    assert to_base(Decimal("3"), teaspoon) == Decimal("3") * to_base(Decimal("1"), teaspoon)
    assert to_base(Decimal("1"), teaspoon) == Decimal("4.9289215938")


def test_humanize_common_fractions(cup):
    assert humanize(Decimal("0.25"), cup) == "¼ cup"
    assert humanize(Decimal("0.5"), cup).startswith("½")
    assert humanize(Decimal("1.5"), cup).startswith("1½")


def test_humanize_plural(cup):
    assert humanize(Decimal("1"), cup) == "1 cup"
    assert humanize(Decimal("2"), cup) == "2 cups"


def test_humanize_falls_back_to_decimal(cup):
    assert humanize(Decimal("0.37"), cup) == "0.37 cup"


def test_humanize_does_not_over_snap_to_fraction(cup):
    """The fraction snap absorbs quantisation noise, not a genuine 0.01 difference —
    ``0.51 cup`` stays a decimal rather than being rounded to "½ cup".
    """
    assert humanize(Decimal("0.51"), cup) == "0.51 cup"


def test_humanize_thirds(cup):
    assert humanize(Decimal("0.333333"), cup).startswith("⅓")
