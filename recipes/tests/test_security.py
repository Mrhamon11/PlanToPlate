"""Recipe visibility / IDOR matrix (``Plan/05-Recipes/test-plan.md``, "Security").

The task 03 machinery is proven generically in ``core/tests``; this proves ``Recipe`` is wired
to it, plus the two nested-write IDOR checks the design calls "the highest-value test in the
task" and the defence-in-depth degradation of an invisible component.

Typeahead-visibility and instruction-escaping tests belong with the HTML screens (05.11 /
05.12) and land there.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from recipes.models import Recipe, RecipeComponent, RecipeStats

pytestmark = pytest.mark.django_db


def _client(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def carol(user_factory):
    return user_factory(username="carol")


def _recipe(owner, cup, **kw):
    defaults = dict(
        name="R", instructions="x", yield_quantity=Decimal("4"), yield_unit=cup, owner=owner
    )
    defaults.update(kw)
    return Recipe.objects.create(**defaults)


# --- IDOR matrix ----------------------------------------------------------------------


def test_unrelated_user_gets_404_not_403_on_retrieve(alice, carol, cup):
    recipe = _recipe(alice, cup, visibility="PRIVATE")
    assert _client(carol).get(f"/api/recipes/{recipe.pk}/").status_code == 404


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_unrelated_user_cannot_write_others_recipe(alice, carol, cup, method):
    recipe = _recipe(alice, cup, name="Alice Private", visibility="PRIVATE")
    response = getattr(_client(carol), method)(
        f"/api/recipes/{recipe.pk}/", {"name": "hijacked"}, format="json"
    )
    assert response.status_code == 404
    recipe.refresh_from_db()
    assert recipe.name == "Alice Private"


def test_list_excludes_others_private(alice, carol, cup):
    _recipe(alice, cup, name="Alice Private", visibility="PRIVATE")
    mine = _recipe(carol, cup, name="Carol Own", visibility="PRIVATE")
    response = _client(carol).get("/api/recipes/")
    assert {row["id"] for row in response.data["results"]} == {mine.pk}


def test_shared_recipe_readable_not_writable(alice, carol, cup):
    recipe = _recipe(alice, cup, name="Alice Shared", visibility="SHARED")
    recipe.shared_with.add(carol)
    client = _client(carol)

    assert client.get(f"/api/recipes/{recipe.pk}/").status_code == 200
    write = client.patch(f"/api/recipes/{recipe.pk}/", {"name": "changed"}, format="json")
    assert write.status_code == 403
    recipe.refresh_from_db()
    assert recipe.name == "Alice Shared"


def test_cannot_share_others_recipe(alice, carol, cup):
    recipe = _recipe(alice, cup, visibility="SHARED")
    recipe.shared_with.add(carol)
    response = _client(carol).post(f"/api/recipes/{recipe.pk}/share/", {"users": [carol.pk]})
    assert response.status_code == 403


def test_shared_with_is_owner_only(alice, carol, user_factory, cup):
    dan = user_factory(username="dan")
    recipe = _recipe(alice, cup, visibility="SHARED")
    recipe.shared_with.add(carol, dan)

    assert _client(carol).get(f"/api/recipes/{recipe.pk}/").data["shared_with"] == []
    assert set(_client(alice).get(f"/api/recipes/{recipe.pk}/").data["shared_with"]) == {
        carol.pk,
        dan.pk,
    }


# --- nested-write IDOR: the highest-value tests in the task --------------------------


def test_cannot_reference_invisible_ingredient(alice, carol, cup, gram, make_ingredient):
    secret = make_ingredient("Alice Truffle", owner=alice, visibility="PRIVATE")
    response = _client(carol).post(
        "/api/recipes/",
        {
            "name": "Probe",
            "instructions": "x",
            "yield_quantity": "4",
            "yield_unit": cup.pk,
            "components": [{"ingredient": secret.pk, "quantity": "1", "unit": gram.pk}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Recipe.objects.filter(name="Probe").exists()


def test_cannot_reference_invisible_subrecipe(alice, carol, cup):
    secret = _recipe(alice, cup, name="Alice Secret Sauce", visibility="PRIVATE")
    response = _client(carol).post(
        "/api/recipes/",
        {
            "name": "Probe",
            "instructions": "x",
            "yield_quantity": "4",
            "yield_unit": cup.pk,
            "components": [{"sub_recipe": secret.pk, "quantity": "1", "unit": cup.pk}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Recipe.objects.filter(name="Probe").exists()


def test_can_reference_own_and_shared_objects(alice, carol, cup, gram, make_ingredient):
    shared_ing = make_ingredient("Alice Shared Salt", owner=alice, visibility="SHARED")
    shared_ing.shared_with.add(carol)
    own_ing = make_ingredient("Carol Pepper", owner=carol, visibility="PRIVATE")

    response = _client(carol).post(
        "/api/recipes/",
        {
            "name": "Legit",
            "instructions": "x",
            "yield_quantity": "4",
            "yield_unit": cup.pk,
            "components": [
                {"ingredient": shared_ing.pk, "quantity": "1", "unit": gram.pk},
                {"ingredient": own_ing.pk, "quantity": "2", "unit": gram.pk},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data


def test_shared_recipe_hides_invisible_component(alice, carol, cup, gram, make_ingredient):
    """Defence in depth: a component whose ingredient is somehow not visible to the viewer
    degrades to the bare name (design.md, "Edge cases"), never a 500 and never the full row.
    """
    recipe = _recipe(alice, cup, name="Leaky", visibility="SHARED")
    recipe.shared_with.add(carol)
    secret = make_ingredient(
        "Alice Private Spice", owner=alice, visibility="PRIVATE", notes="secret blend"
    )
    RecipeComponent.objects.create(
        recipe=recipe, ingredient=secret, quantity=Decimal("1"), unit=gram
    )

    response = _client(carol).get(f"/api/recipes/{recipe.pk}/")

    assert response.status_code == 200
    component = response.data["components"][0]
    assert component["ingredient_name"] == "Alice Private Spice"
    # the full ingredient row (its notes, density, tags) is never serialized into a component
    assert "notes" not in component
    assert "density_g_per_ml" not in component


# --- typeahead pickers: never leak an invisible name, never offer a cycle -------------


def test_typeahead_only_returns_visible(alice, carol, cup, gram, make_ingredient):
    """The ingredient and sub-recipe pickers filter through visible_to — a typeahead is a
    classic place to leak the existence of a private object by name (design.md, "Security
    notes")."""
    make_ingredient("Alice Secret Truffle", owner=alice, visibility="PRIVATE")
    _recipe(alice, cup, name="Alice Secret Sauce", visibility="PRIVATE")
    client = _client(carol)

    ingredients = client.get("/recipes/typeahead/ingredients/", {"q": "Secret"})
    assert ingredients.status_code == 200
    assert "Alice Secret Truffle" not in ingredients.content.decode()

    sub_recipes = client.get("/recipes/typeahead/sub-recipes/", {"q": "Secret"})
    assert sub_recipes.status_code == 200
    assert "Alice Secret Sauce" not in sub_recipes.content.decode()


def test_subrecipe_typeahead_excludes_cycles(alice, cup):
    """A candidate that would create a cycle is absent from the picker, not merely rejected on
    submit (design.md, "UI"; test-plan.md "Security")."""
    parent = _recipe(alice, cup, name="Parent Stew")
    child = _recipe(alice, cup, name="Child Sauce")
    RecipeComponent.objects.create(recipe=parent, sub_recipe=child, quantity=Decimal("1"), unit=cup)
    # An unrelated recipe with the same search prefix — proves the filter is the cycle, not
    # the query.
    _recipe(alice, cup, name="Parent Salad")
    client = _client(alice)

    # Editing `child`: offering `parent` would close child -> parent -> child.
    response = client.get("/recipes/typeahead/sub-recipes/", {"q": "Parent", "recipe": child.pk})

    body = response.content.decode()
    assert response.status_code == 200
    assert "Parent Stew" not in body
    assert "Parent Salad" in body


# --- stats are private --------------------------------------------------------------


def test_stats_are_private(alice, carol, cup):
    recipe = _recipe(alice, cup, visibility="PUBLIC")
    RecipeStats.objects.create(user=alice, recipe=recipe, rating=5, is_favorite=True)

    # carol reads her own (empty) stats, never alice's
    carol_view = _client(carol).get(f"/api/recipes/{recipe.pk}/stats/")
    assert carol_view.status_code == 200
    assert carol_view.data["rating"] is None
    assert carol_view.data["is_favorite"] is False

    # carol's write touches only carol's row
    _client(carol).put(f"/api/recipes/{recipe.pk}/stats/", {"rating": 1}, format="json")
    assert RecipeStats.objects.get(user=alice, recipe=recipe).rating == 5
    assert RecipeStats.objects.get(user=carol, recipe=recipe).rating == 1


def test_cannot_write_stats_on_invisible_recipe(alice, carol, cup):
    recipe = _recipe(alice, cup, visibility="PRIVATE")
    assert _client(carol).post(f"/api/recipes/{recipe.pk}/made/").status_code == 404
    assert (
        _client(carol)
        .put(f"/api/recipes/{recipe.pk}/stats/", {"rating": 3}, format="json")
        .status_code
        == 404
    )
