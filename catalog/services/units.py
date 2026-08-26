"""Unit conversion — the correctness core of task 04 (design.md, "Conversion service").

Rules:

- **Same dimension, MASS or VOLUME:** always works. ``quantity * from.factor / to.factor``.
- **Same dimension, COUNT:** works only between units of the same ``count_family``
  (``each``/``dozen``/``half dozen`` on their 1/6/12 ratios). A packaging or piece unit
  (can, slice, clove, …) is its own family and converts only to itself — "1 can" and
  "2 slices" have no fixed ratio, so the service refuses rather than returning a number
  (MILESTONES.md decision D34).
- **MASS ↔ VOLUME:** only when the ingredient carries a density. Otherwise raise
  ``IncompatibleUnits`` — never guess a density, because a wrong conversion produces a
  confidently incorrect shopping list.
- **COUNT ↔ MASS/VOLUME:** never.

All arithmetic is ``Decimal`` with explicit quantisation. ``float`` never appears here.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Protocol

from catalog.exceptions import IncompatibleUnits
from catalog.models import Dimension, Unit


class _HasDensity(Protocol):
    """The only attribute the conversion service reads off an ingredient. Stated as a
    ``Protocol`` so a caller can pass a real ``Ingredient`` or any stand-in exposing the same
    field (``design.md`` names ``Ingredient | None``; the service needs nothing more specific).
    """

    density_g_per_ml: Decimal | None


#: Conversion results are quantised to this many decimal places. Six is far beyond kitchen
#: precision (a microlitre) yet small enough that a ``convert`` → ``convert`` round trip does
#: not visibly drift.
_QUANTUM = Decimal("0.000001")

#: ``(denominator, {numerator: glyph})`` pairs ``humanize`` snaps a fractional remainder to.
#: Deliberately shallow — quarters, thirds, halves — so an odd decimal like ``0.37`` falls back
#: to a plain number instead of being forced into a nonsense fraction.
_FRACTIONS: list[tuple[int, dict[int, str]]] = [
    (2, {1: "½"}),
    (3, {1: "⅓", 2: "⅔"}),
    (4, {1: "¼", 3: "¾"}),
]

#: How close a scaled remainder must land to an integer before ``humanize`` treats it as that
#: fraction. Applied to ``remainder * denominator``, so the effective tolerance on the whole
#: unit is ``_FRACTION_SNAP / denominator`` — a thousandth at worst. Wide enough to absorb the
#: 1e-6 conversion quantum (``0.333333 * 3 = 0.999999``) and 4dp user input, narrow enough that
#: ``0.51 cup`` is not silently rendered "½ cup".
_FRACTION_SNAP = Decimal("0.001")


def _as_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def to_base(quantity: Decimal | int | str, unit: Unit) -> Decimal:
    """``quantity`` expressed in ``unit``'s dimension base (gram, millilitre, or each).

    Returns the raw product, **not** quantised: ``to_base`` is an intermediate value (task 05
    sums many of them before anything is displayed), and quantising here would make
    ``3 * to_base(1, tsp)`` disagree with ``to_base(3, tsp)``. Quantisation happens in
    ``convert`` and at the display boundary.
    """
    return _as_decimal(quantity) * unit.to_base_factor


def convert(
    quantity: Decimal | int | str,
    from_unit: Unit,
    to_unit: Unit,
    ingredient: _HasDensity | None = None,
) -> Decimal:
    """Convert ``quantity`` from ``from_unit`` to ``to_unit``.

    ``ingredient`` (anything exposing ``density_g_per_ml``) is consulted only for a MASS ↔
    VOLUME conversion. Raises ``IncompatibleUnits`` when the conversion cannot be done without
    inventing data.
    """
    q = _as_decimal(quantity)

    if _same_unit(from_unit, to_unit):
        return q

    if from_unit.dimension == to_unit.dimension:
        if from_unit.dimension == Dimension.COUNT and not _same_count_family(from_unit, to_unit):
            raise IncompatibleUnits(
                from_unit,
                to_unit,
                f"'{from_unit.name}' and '{to_unit.name}' are counted in different ways and "
                f"have no fixed ratio between them",
            )
        return _quantize(q * from_unit.to_base_factor / to_unit.to_base_factor)

    if Dimension.COUNT in (from_unit.dimension, to_unit.dimension):
        raise IncompatibleUnits(
            from_unit,
            to_unit,
            "a counted unit only relates to a mass or a volume through an "
            "ingredient-specific weight per item, which is out of scope",
        )

    # Only MASS ↔ VOLUME remains.
    density = getattr(ingredient, "density_g_per_ml", None)
    if density is None:
        raise IncompatibleUnits(
            from_unit,
            to_unit,
            "converting between mass and volume needs the ingredient's density, which is "
            "not set — refusing rather than guessing a value",
        )
    density = _as_decimal(density)

    from_base = q * from_unit.to_base_factor
    if from_unit.dimension == Dimension.MASS:
        target_base = from_base / density  # grams → millilitres
    else:
        target_base = from_base * density  # millilitres → grams
    return _quantize(target_base / to_unit.to_base_factor)


def humanize(quantity: Decimal | int | str, unit: Unit) -> str:
    """Render ``quantity`` and ``unit`` the way a recipe would read it: "¼ cup", "1½ cups",
    "2 cups", and — when no tidy fraction fits — "0.37 cup".
    """
    q = _as_decimal(quantity)
    label = unit.label_for(q)

    whole = int(q.to_integral_value(rounding=ROUND_DOWN))
    remainder = q - whole

    glyph = _fraction_glyph(remainder)
    if glyph is not None:
        return f"{glyph} {label}" if whole == 0 else f"{whole}{glyph} {label}"

    return f"{_plain_number(q)} {label}"


def _same_unit(from_unit: Unit, to_unit: Unit) -> bool:
    """Same-unit conversion is the identity — return the input untouched by factor arithmetic
    (design.md, "Edge cases"). Compares the row when both are saved, falling back to object
    identity for unsaved instances.
    """
    if from_unit.pk is not None or to_unit.pk is not None:
        return from_unit.pk == to_unit.pk
    return from_unit is to_unit


def _same_count_family(from_unit: Unit, to_unit: Unit) -> bool:
    """Two COUNT units interconvert only if they share a non-empty ``count_family``. An empty
    family means "singleton" — it relates to nothing but itself, which the identity check
    upstream has already handled by the time this runs.
    """
    return bool(from_unit.count_family) and from_unit.count_family == to_unit.count_family


def _fraction_glyph(remainder: Decimal) -> str | None:
    if remainder <= 0:
        return None
    for denominator, glyphs in _FRACTIONS:
        scaled = remainder * denominator
        nearest = scaled.to_integral_value(rounding=ROUND_HALF_UP)
        if abs(scaled - nearest) <= _FRACTION_SNAP and int(nearest) in glyphs:
            return glyphs[int(nearest)]
    return None


def _plain_number(q: Decimal) -> str:
    normalised = q.normalize()
    if normalised == normalised.to_integral_value():
        return str(normalised.quantize(Decimal(1)))
    return format(normalised, "f")
