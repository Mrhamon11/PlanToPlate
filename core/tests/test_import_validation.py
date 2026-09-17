"""Bulk JSON import — the dry-run validator (task 09.9).

Every row of ``Plan/09-Admin-Control-Center/test-plan.md``'s "Import validation" table:
path-qualified errors, the denial-of-service caps, unknown version, in-file duplicates, and
the guarantee that a failed validation writes nothing.
"""

from __future__ import annotations

import json

import pytest

from catalog.models import Ingredient
from core.schemas import MAX_NESTING_DEPTH
from core.services.importer import ImportValidationError, validate
from recipes.models import Recipe

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog(gram, cup, make_tag):
    """A minimal shared vocabulary: units ``g`` / ``cup`` and one tag."""
    make_tag("quick")
    return {"gram": gram, "cup": cup}


def _valid_file() -> dict:
    return {
        "version": 1,
        "ingredients": [{"name": "Flour", "default_unit": "g", "tags": ["quick"]}],
        "recipes": [
            {
                "name": "Bread",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "instructions": "Bake.",
                "role": "CARB",
                "components": [{"ingredient": "Flour", "quantity": "500", "unit": "g"}],
            }
        ],
        "dishes": [{"name": "Bread plate", "recipes": ["Bread"]}],
    }


def _validate(data, *, owner):
    return validate(json.dumps(data), owner=owner)


def test_valid_file_passes(catalog, alice):
    plan = _validate(_valid_file(), owner=alice)

    assert [i.name for i in plan.ingredients] == ["Flour"]
    assert [r.name for r in plan.recipes] == ["Bread"]
    assert [d.name for d in plan.dishes] == ["Bread plate"]


def test_unknown_unit_reports_path(catalog, alice):
    data = _valid_file()
    data["recipes"] = [
        {"name": f"R{n}", "yield_quantity": "1", "yield_unit": "cup", "components": []}
        for n in range(4)
    ]
    data["recipes"][3]["components"] = [
        {"ingredient": "Flour", "quantity": "1", "unit": "g"},
        {"ingredient": "Flour", "quantity": "1", "unit": "cupp"},
    ]

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    paths = {str(p) for p in excinfo.value.problems}
    assert "recipes[3].components[1].unit: unknown unit 'cupp'" in paths


def test_unknown_tag_reports_path(catalog, alice):
    data = _valid_file()
    data["ingredients"][0]["tags"] = ["nonexistent-tag"]

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert any(p.path == "ingredients[0].tags[0]" for p in excinfo.value.problems)


def test_missing_required_field_reports_path(catalog, alice):
    data = _valid_file()
    del data["recipes"][0]["yield_unit"]

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert any(p.path == "recipes[0].yield_unit" for p in excinfo.value.problems)


def test_duplicate_name_in_file_rejected(catalog, alice):
    data = _valid_file()
    data["ingredients"].append({"name": "flour", "default_unit": "g"})

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert any(
        p.path == "ingredients[1].name" and "duplicate" in p.message for p in excinfo.value.problems
    )


def test_file_size_cap_enforced(alice):
    raw = b'{"version": 1}' + b" " * (5 * 1024 * 1024)

    with pytest.raises(ImportValidationError) as excinfo:
        validate(raw, owner=alice)

    assert "larger than" in str(excinfo.value.problems[0])


def test_object_count_cap_enforced(catalog, alice):
    data = {
        "version": 1,
        "ingredients": [{"name": f"i{n}", "default_unit": "g"} for n in range(1001)],
    }

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert "cap is 1000" in str(excinfo.value.problems[0])


def test_nesting_depth_cap_enforced(alice):
    nested = "[" * (MAX_NESTING_DEPTH + 2) + "]" * (MAX_NESTING_DEPTH + 2)
    raw = '{"version": 1, "x": ' + nested + "}"

    with pytest.raises(ImportValidationError) as excinfo:
        validate(raw, owner=alice)

    assert "nests" in str(excinfo.value.problems[0])


def test_malformed_json_reports_position(alice):
    with pytest.raises(ImportValidationError) as excinfo:
        validate('{"version": 1,,}', owner=alice)

    assert "line" in str(excinfo.value.problems[0])
    assert "column" in str(excinfo.value.problems[0])


def test_unknown_version_rejected(catalog, alice):
    data = _valid_file()
    data["version"] = 99

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert any(p.path == "version" for p in excinfo.value.problems)


def test_incompatible_sub_recipe_unit_reports_path(catalog, alice, make_recipe):
    """A sub-recipe component whose unit cannot be scaled to the sub-recipe's yield unit is a
    row the flattener can never turn into a shopping list — the importer is the third
    ``RecipeComponent`` write path and must refuse it here, exactly as the REST and HTML paths
    do (CLAUDE.md §6). Covers both an in-file and an already-existing sub-recipe.
    """
    make_recipe("Existing Stock", owner=alice, yield_unit=catalog["gram"])
    data = _valid_file()
    data["ingredients"] = [{"name": "Flour", "default_unit": "g"}]
    data["recipes"] = [
        {
            "name": "In-file Stock",
            "yield_quantity": "500",
            "yield_unit": "g",
            "instructions": "Simmer.",
            "components": [{"ingredient": "Flour", "quantity": "1", "unit": "g"}],
        },
        {
            "name": "Soup",
            "yield_quantity": "1",
            "yield_unit": "cup",
            "instructions": "Combine.",
            "components": [
                {"sub_recipe": "In-file Stock", "quantity": "2", "unit": "cup"},
                {"sub_recipe": "Existing Stock", "quantity": "2", "unit": "cup"},
            ],
        },
    ]
    data["dishes"] = []

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    messages = {(p.path, p.message) for p in excinfo.value.problems}
    assert any(
        path == "recipes[1].components[0].unit" and "In-file Stock" in msg for path, msg in messages
    )
    assert any(
        path == "recipes[1].components[1].unit" and "Existing Stock" in msg
        for path, msg in messages
    )


def test_compatible_sub_recipe_unit_passes(catalog, alice):
    data = _valid_file()
    data["ingredients"] = [{"name": "Flour", "default_unit": "g"}]
    data["recipes"] = [
        {
            "name": "Stock",
            "yield_quantity": "2",
            "yield_unit": "cup",
            "instructions": "Simmer.",
            "components": [{"ingredient": "Flour", "quantity": "1", "unit": "g"}],
        },
        {
            "name": "Soup",
            "yield_quantity": "1",
            "yield_unit": "cup",
            "instructions": "Combine.",
            "components": [{"sub_recipe": "Stock", "quantity": "1", "unit": "cup"}],
        },
    ]
    data["dishes"] = []

    plan = _validate(data, owner=alice)

    assert [r.name for r in plan.recipes] == ["Stock", "Soup"]


def test_quantity_magnitude_cap_enforced(catalog, alice):
    """A quantity wider than the ``DecimalField`` column is a path-qualified problem, not an
    unhandled ``DataError`` from inside ``execute``.
    """
    data = _valid_file()
    data["recipes"][0]["components"][0]["quantity"] = "1E40"

    with pytest.raises(ImportValidationError) as excinfo:
        _validate(data, owner=alice)

    assert any(
        p.path == "recipes[0].components[0].quantity" and "out of range" in p.message
        for p in excinfo.value.problems
    )


def test_validation_writes_nothing(catalog, alice):
    data = _valid_file()
    data["recipes"][0]["components"][0]["unit"] = "cupp"  # forces a failure

    ingredients_before = Ingredient.objects.count()
    recipes_before = Recipe.objects.count()

    with pytest.raises(ImportValidationError):
        _validate(data, owner=alice)

    assert Ingredient.objects.count() == ingredients_before
    assert Recipe.objects.count() == recipes_before
