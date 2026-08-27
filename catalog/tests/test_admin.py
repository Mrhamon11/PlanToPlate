"""``IngredientAdminForm`` — the owner-XOR-``is_system`` rule as a form error, not a 500
(04.1-04.5 review, finding #10)."""

from __future__ import annotations

import pytest

from catalog.admin import IngredientAdminForm

pytestmark = pytest.mark.django_db


def _data(**overrides) -> dict:
    base = {
        "name": "Test",
        "is_staple": False,
        "visibility": "PRIVATE",
        "tags": [],
    }
    base.update(overrides)
    return base


def test_system_ingredient_with_owner_is_a_form_error(gram, user_factory):
    alice = user_factory(username="alice")

    form = IngredientAdminForm(
        data=_data(default_unit=gram.pk, is_system=True, owner=alice.pk, visibility="PUBLIC")
    )

    assert not form.is_valid()
    assert "must not have an owner" in str(form.errors)


def test_non_system_ingredient_without_owner_is_a_form_error(gram):
    form = IngredientAdminForm(data=_data(default_unit=gram.pk, is_system=False))

    assert not form.is_valid()
    assert "must have an owner" in str(form.errors)


def test_valid_system_ingredient_passes(gram):
    form = IngredientAdminForm(data=_data(default_unit=gram.pk, is_system=True))

    assert form.is_valid(), form.errors


def test_valid_user_ingredient_passes(gram, user_factory):
    alice = user_factory(username="alice")
    form = IngredientAdminForm(data=_data(default_unit=gram.pk, is_system=False, owner=alice.pk))

    assert form.is_valid(), form.errors
