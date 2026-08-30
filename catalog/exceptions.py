"""Domain exceptions for the catalog app."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog.models import Unit


class IncompatibleUnits(Exception):  # noqa: N818 - name fixed by design.md ("Conversion service")
    """A requested unit conversion cannot be performed without fabricating data.

    Raised for MASS ↔ VOLUME when the ingredient has no density, and for any conversion
    touching a COUNT unit. Carries both units and a human-readable reason so the API layer can
    return a 400 that names what went wrong rather than a bare error (design.md, "API").
    """

    def __init__(self, from_unit: Unit, to_unit: Unit, reason: str) -> None:
        self.from_unit = from_unit
        self.to_unit = to_unit
        self.reason = reason
        super().__init__(f"Cannot convert {from_unit.name} to {to_unit.name}: {reason}")
