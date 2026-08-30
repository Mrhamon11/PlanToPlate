"""Shared API exception helpers.

``Conflict`` / ``conflict_from_protected_error`` translate a ``django.db.models.ProtectedError``
— raised when ``on_delete=PROTECT`` blocks a delete — into an HTTP 409 whose body names the
objects still referencing the row, rather than letting the ``ProtectedError`` surface as a bare
500 (``Plan/04-Units-And-Ingredients/design.md``, "API": "DELETE ... must fail with 409 and
name the recipes — silent cascade would gut people's recipes").
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Model, ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException

_MAX_NAMED = 10


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This object is still in use and cannot be deleted."
    default_code = "conflict"


def describe_blocking_objects(objects: Iterable[Model], *, limit: int = _MAX_NAMED) -> str:
    """A short human list of the objects blocking a delete: ``"Carbonara, Ragu and 3 more"``."""
    named = [str(obj) for obj in objects]
    named.sort()
    head = named[:limit]
    remainder = len(named) - len(head)
    if remainder > 0:
        head.append(f"and {remainder} more")
    return ", ".join(head)


def conflict_from_protected_error(exc: ProtectedError) -> Conflict:
    """Build the 409 for ``exc``. ``exc.protected_objects`` is every row whose ``PROTECT``
    foreign key points at the object being deleted.
    """
    blocking = describe_blocking_objects(exc.protected_objects)
    detail = (
        f"Cannot delete this — it is still used by: {blocking}. Remove those references first."
        if blocking
        else "Cannot delete this — other objects still reference it."
    )
    return Conflict(detail)
