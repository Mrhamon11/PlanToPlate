"""Cycle-guard tests (``Plan/05-Recipes/test-plan.md``, "Cycle guard").

The three write-path guard tests (serializer / form / admin) land with subtasks 05.7 / 05.8 /
05.12, which add those write paths. This module covers the guard service itself.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from recipes.models import Recipe
from recipes.services.graph import (
    MAX_DEPTH,
    CycleError,
    DepthExceededError,
    assert_no_cycle,
    recipe_depth,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def chain(make_recipe, add_sub_recipe, cup):
    """Build ``count`` recipes r0..r(count-1) linked r0 -> r1 -> ... (each contains the next),
    bypassing the guard so the guard itself can be tested against the result.
    """

    def _build(count: int):
        recipes = [make_recipe(name=f"r{i}") for i in range(count)]
        for parent, child in zip(recipes, recipes[1:], strict=False):
            add_sub_recipe(parent, child, 1, cup)
        return recipes

    return _build


def test_self_reference_rejected(make_recipe):
    recipe = make_recipe(name="Self")
    with pytest.raises(CycleError):
        assert_no_cycle(recipe, recipe)


def test_two_hop_cycle_rejected(make_recipe, add_sub_recipe, cup):
    a = make_recipe(name="A")
    b = make_recipe(name="B")
    add_sub_recipe(a, b, 1, cup)

    with pytest.raises(CycleError):
        assert_no_cycle(b, a)


def test_deep_cycle_rejected(make_recipe, add_sub_recipe, cup):
    a = make_recipe(name="A")
    b = make_recipe(name="B")
    c = make_recipe(name="C")
    d = make_recipe(name="D")
    add_sub_recipe(a, b, 1, cup)
    add_sub_recipe(b, c, 1, cup)
    add_sub_recipe(c, d, 1, cup)

    with pytest.raises(CycleError):
        assert_no_cycle(d, a)


def test_cycle_error_names_the_chain(make_recipe, add_sub_recipe, cup):
    a = make_recipe(name="Alfredo")
    b = make_recipe(name="Bechamel")
    add_sub_recipe(a, b, 1, cup)

    with pytest.raises(CycleError) as excinfo:
        assert_no_cycle(b, a)

    message = str(excinfo.value)
    assert "Alfredo" in message
    assert "Bechamel" in message
    assert excinfo.value.chain[0] == excinfo.value.chain[-1] == "Bechamel"


def test_valid_dag_allowed(make_recipe, add_sub_recipe, cup):
    a = make_recipe(name="A")
    b = make_recipe(name="B")
    c = make_recipe(name="C")
    d = make_recipe(name="D")
    add_sub_recipe(a, b, 1, cup)
    add_sub_recipe(a, c, 1, cup, position=1)
    add_sub_recipe(b, d, 1, cup)

    # C -> D closes the diamond, not a cycle.
    assert_no_cycle(c, d)


def test_max_depth_enforced(chain, make_recipe):
    recipes = chain(MAX_DEPTH + 1)  # r0..r5, five edges below r0
    extra = make_recipe(name="extra")

    with pytest.raises(DepthExceededError):
        assert_no_cycle(recipes[-1], extra)


def test_depth_five_allowed(chain, make_recipe):
    recipes = chain(MAX_DEPTH)  # r0..r4, four edges below r0
    extra = make_recipe(name="extra")

    assert_no_cycle(recipes[-1], extra)  # would be the fifth edge — allowed
    assert recipe_depth(recipes[0]) == MAX_DEPTH - 1


# --- write-path enforcement: the serializer (05.7) ----------------------------------
# The form (05.12) and admin write paths land with their own subtasks; test-plan wants a
# separate proof for each — a guard on one path is not a guard.


def test_guard_enforced_on_serializer(user_factory, make_recipe, add_sub_recipe, cup):
    me = user_factory(username="me")
    client = APIClient()
    client.force_login(me)

    a = make_recipe(name="A", owner=me)
    b = make_recipe(name="B", owner=me)
    add_sub_recipe(b, a, 1, cup)  # B already contains A

    # Adding B as a sub-recipe of A would close the loop A -> B -> A.
    response = client.patch(
        f"/api/recipes/{a.pk}/",
        {"components": [{"sub_recipe": b.pk, "quantity": "1", "unit": cup.pk}]},
        format="json",
    )

    assert response.status_code == 400
    assert "cycle" in str(response.data).lower()
    assert not a.components.exists()


def test_guard_enforced_on_form(user_factory, make_recipe, add_sub_recipe, cup):
    """The HTML recipe form is the second of the three write paths the guard must cover
    (test-plan.md, "Cycle guard"). Editing A to contain B, when B already contains A, is
    refused and nothing is written."""
    me = user_factory(username="me")
    client = Client()
    client.force_login(me)

    a = make_recipe(name="A", owner=me)
    b = make_recipe(name="B", owner=me)
    add_sub_recipe(b, a, 1, cup)  # B already contains A

    response = client.post(
        reverse("recipes:recipe-update", args=[a.pk]),
        {
            "name": "A",
            "instructions": "x",
            "yield_quantity": "4",
            "yield_unit": cup.pk,
            "role": "OTHER",
            "component_kind": ["sub_recipe"],
            "component_ref": [str(b.pk)],
            "component_quantity": ["1"],
            "component_unit": [str(cup.pk)],
            "component_note": [""],
        },
    )

    assert response.status_code == 200  # re-rendered form, not a redirect
    assert "cycle" in response.content.decode().lower()
    assert not a.components.exists()


def test_serializer_rejects_depth_exceeding_write(user_factory, make_recipe, add_sub_recipe, cup):
    me = user_factory(username="me")
    client = APIClient()
    client.force_login(me)

    chain = [make_recipe(name=f"d{i}", owner=me) for i in range(MAX_DEPTH + 1)]
    for parent, child in zip(chain, chain[1:], strict=False):
        add_sub_recipe(parent, child, 1, cup)
    top = make_recipe(name="top", owner=me)

    response = client.patch(
        f"/api/recipes/{top.pk}/",
        {"components": [{"sub_recipe": chain[0].pk, "quantity": "1", "unit": cup.pk}]},
        format="json",
    )

    assert response.status_code == 400
    assert Recipe.objects.get(pk=top.pk).components.count() == 0
