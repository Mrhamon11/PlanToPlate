"""Ingredient service helpers shared by the REST serializer and the HTML form, so the
name-uniqueness rule (design.md, "Ingredient": one owner cannot hold two rows with the same
name, case-insensitively) is expressed once rather than re-derived per layer.

The database's functional unique constraints are the actual enforcement point; these helpers
only move the failure from an ``IntegrityError`` 500 to a 400/form error at the boundary.
"""

from __future__ import annotations

from catalog.models import Ingredient


def owner_has_ingredient_named(owner: object, name: str, *, exclude_pk: int | None = None) -> bool:
    """True if ``owner`` already owns an ingredient whose name matches ``name`` case- and
    whitespace-insensitively. ``exclude_pk`` skips the row being edited.
    """
    if owner is None:
        return False
    clash = Ingredient.objects.filter(owner=owner, name__iexact=name.strip())
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    return clash.exists()
