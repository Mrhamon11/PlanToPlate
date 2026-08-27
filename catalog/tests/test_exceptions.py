"""``core.exceptions`` — the ``ProtectedError`` -> HTTP 409 translation (04.8).

The real end-to-end ``test_delete_in_use_returns_409`` (a live ``RecipeComponent`` PROTECTing
an ingredient) is deferred to task 05, since ``recipes/models.py`` is still empty. Until then
the handler is proven here against a synthetically constructed ``ProtectedError``, and through
the viewset in ``test_api.py::test_delete_raising_protected_error_becomes_409``.
"""

from __future__ import annotations

import pytest
from django.db.models import ProtectedError
from rest_framework import status

from core.exceptions import Conflict, conflict_from_protected_error, describe_blocking_objects


class _Blocker:
    def __init__(self, label: str) -> None:
        self.label = label

    def __str__(self) -> str:
        return self.label


def test_conflict_status_is_409():
    assert Conflict.status_code == status.HTTP_409_CONFLICT


def test_describe_blocking_objects_sorts_and_truncates():
    objects = [_Blocker(f"Recipe {i:02d}") for i in range(15)]

    described = describe_blocking_objects(objects, limit=3)

    assert described.startswith("Recipe 00, Recipe 01, Recipe 02")
    assert "and 12 more" in described


def test_conflict_from_protected_error_names_the_blocking_objects():
    exc = ProtectedError("in use", {_Blocker("Carbonara"), _Blocker("Cacio e Pepe")})

    conflict = conflict_from_protected_error(exc)

    assert conflict.status_code == status.HTTP_409_CONFLICT
    detail = str(conflict.detail)
    assert "Carbonara" in detail
    assert "Cacio e Pepe" in detail


def test_conflict_from_protected_error_with_no_named_objects():
    exc = ProtectedError("in use", set())

    conflict = conflict_from_protected_error(exc)

    assert conflict.status_code == status.HTTP_409_CONFLICT
    assert "reference" in str(conflict.detail).lower()


@pytest.mark.django_db
def test_html_delete_view_translates_protected_error(
    client, user_factory, make_ingredient, monkeypatch
):
    """The HTML ``IngredientDeleteView`` path (04.10): a PROTECTed delete surfaces as a flash
    message and a redirect back to the ingredient, not a 500.
    """
    from django.urls import reverse

    from catalog.models import Ingredient
    from core.models import Visibility

    user = user_factory(username="me")
    client.force_login(user)
    ingredient = make_ingredient(name="Doomed", owner=user, visibility=Visibility.PRIVATE)
    blocker = _Blocker("Sunday Roast")

    def boom(self, *args, **kwargs):
        raise ProtectedError("in use", {blocker})

    monkeypatch.setattr("catalog.models.Ingredient.delete", boom)

    response = client.post(reverse("catalog:ingredient-delete", args=[ingredient.pk]))

    assert response.status_code == 302
    assert response.url == reverse("catalog:ingredient-detail", args=[ingredient.pk])
    assert Ingredient.objects.filter(pk=ingredient.pk).exists()
