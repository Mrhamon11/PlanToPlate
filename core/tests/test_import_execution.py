"""Bulk JSON import — the executor (task 09.10 / 09.11).

Every row of ``Plan/09-Admin-Control-Center/test-plan.md``'s "Import execution" table:
atomic all-or-nothing writes, two-pass forward references, ``owner`` taken only from the
argument, the cycle guard, skip / update modes, dry runs, visible-only reference resolution,
and the management command matching the admin page.
"""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from catalog.models import Ingredient
from core.services.importer import (
    SKIP_EXISTING,
    UPDATE_EXISTING,
    ImportValidationError,
    run_import,
)
from meals.models import Dish
from recipes.models import Recipe

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog(gram, cup):
    return {"gram": gram, "cup": cup}


def _file(**overrides) -> dict:
    data = {
        "version": 1,
        "ingredients": [{"name": "Flour", "default_unit": "g"}],
        "recipes": [
            {
                "name": "Bread",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "instructions": "Bake.",
                "components": [{"ingredient": "Flour", "quantity": "500", "unit": "g"}],
            }
        ],
        "dishes": [{"name": "Bread plate", "recipes": ["Bread"]}],
    }
    data.update(overrides)
    return data


def _run(data, *, owner, **kwargs):
    return run_import(raw=json.dumps(data), owner=owner, **kwargs)


def test_import_creates_objects(catalog, alice):
    report = _run(_file(), owner=alice)

    bread = Recipe.objects.get(owner=alice, name="Bread")
    assert bread.components.get().ingredient.name == "Flour"
    assert Dish.objects.get(owner=alice, name="Bread plate").components.get().recipe == bread
    assert report.created == {"ingredients": 1, "recipes": 1, "dishes": 1}


def test_import_is_atomic(catalog, alice):
    """A chain of 7 recipes nests past ``MAX_DEPTH`` — it passes shape validation but the
    cycle/depth guard fires mid-execution. Nothing may survive.
    """
    chain = [
        {
            "name": f"R{n}",
            "yield_quantity": "1",
            "yield_unit": "cup",
            "components": [{"sub_recipe": f"R{n + 1}", "quantity": "1", "unit": "cup"}],
        }
        for n in range(6)
    ]
    chain.append({"name": "R6", "yield_quantity": "1", "yield_unit": "cup", "components": []})

    with pytest.raises(ImportValidationError):
        _run(_file(recipes=chain, dishes=[]), owner=alice)

    assert not Recipe.objects.filter(owner=alice).exists()
    assert not Ingredient.objects.filter(owner=alice).exists()


def test_forward_references_resolved(catalog, alice):
    data = _file(
        recipes=[
            {
                "name": "Pasta",
                "yield_quantity": "2",
                "yield_unit": "cup",
                "components": [{"sub_recipe": "Sauce", "quantity": "1", "unit": "cup"}],
            },
            {
                "name": "Sauce",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"ingredient": "Flour", "quantity": "1", "unit": "g"}],
            },
        ],
        dishes=[],
    )

    _run(data, owner=alice)

    pasta = Recipe.objects.get(owner=alice, name="Pasta")
    assert pasta.components.get().sub_recipe.name == "Sauce"


def test_owner_set_from_argument(catalog, alice):
    _run(_file(), owner=alice)

    assert all(r.owner == alice for r in Recipe.objects.all())
    assert all(i.owner == alice for i in Ingredient.objects.filter(is_system=False))
    assert all(d.owner == alice for d in Dish.objects.all())


def test_owner_in_payload_ignored(catalog, alice, bob):
    """The key import security test: a file claiming another owner cannot escalate or forge
    attribution.
    """
    data = _file()
    data["recipes"][0]["owner"] = bob.username
    data["ingredients"][0]["owner"] = bob.username

    _run(data, owner=alice)

    assert Recipe.objects.get(name="Bread").owner == alice
    assert Ingredient.objects.get(name="Flour").owner == alice
    assert not Recipe.objects.filter(owner=bob).exists()


def test_is_system_in_payload_ignored(catalog, alice):
    data = _file()
    data["ingredients"][0]["is_system"] = True
    data["recipes"][0]["is_system"] = True

    _run(data, owner=alice)

    assert Ingredient.objects.get(name="Flour").is_system is False
    assert Recipe.objects.get(name="Bread").is_system is False


def test_cycle_in_import_rejected(catalog, alice):
    data = _file(
        recipes=[
            {
                "name": "A",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"sub_recipe": "B", "quantity": "1", "unit": "cup"}],
            },
            {
                "name": "B",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"sub_recipe": "A", "quantity": "1", "unit": "cup"}],
            },
        ],
        dishes=[],
    )

    with pytest.raises(ImportValidationError) as excinfo:
        _run(data, owner=alice)

    assert any("cycle" in p.message.lower() for p in excinfo.value.problems)
    assert not Recipe.objects.filter(owner=alice).exists()


def test_skip_existing_default(catalog, alice):
    Recipe.objects.create(
        owner=alice,
        name="Bread",
        instructions="ORIGINAL",
        yield_quantity=1,
        yield_unit=catalog["cup"],
    )

    report = _run(_file(dishes=[]), owner=alice)

    assert Recipe.objects.get(owner=alice, name="Bread").instructions == "ORIGINAL"
    assert report.skipped["recipes"] == 1
    assert report.created["recipes"] == 0


def test_update_existing_mode(catalog, alice):
    existing = Recipe.objects.create(
        owner=alice,
        name="Bread",
        instructions="ORIGINAL",
        yield_quantity=1,
        yield_unit=catalog["cup"],
    )

    report = _run(_file(dishes=[]), owner=alice, mode=UPDATE_EXISTING)

    existing.refresh_from_db()
    assert existing.instructions == "Bake."
    assert existing.components.get().ingredient.name == "Flour"
    assert report.updated["recipes"] == 1


def test_dry_run_writes_nothing(catalog, alice):
    report = _run(_file(), owner=alice, dry_run=True)

    assert not Recipe.objects.filter(owner=alice).exists()
    assert not Dish.objects.filter(owner=alice).exists()
    assert report.dry_run is True
    assert report.created == {"ingredients": 1, "recipes": 1, "dishes": 1}


def test_import_resolves_against_visible_objects_only(catalog, alice, bob, make_ingredient):
    """Referencing a name that matches only another user's *private* ingredient does not bind
    to it — the import creates its own, owned by the importing owner.
    """
    bob_saffron = make_ingredient("Saffron", owner=bob)
    data = _file(
        ingredients=[{"name": "Saffron", "default_unit": "g"}],
        recipes=[
            {
                "name": "Rice",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"ingredient": "Saffron", "quantity": "1", "unit": "g"}],
            }
        ],
        dishes=[],
    )

    _run(data, owner=alice)

    alice_saffron = Ingredient.objects.get(owner=alice, name="Saffron")
    assert alice_saffron != bob_saffron
    assert Recipe.objects.get(name="Rice").components.get().ingredient == alice_saffron


def test_import_binds_owner_own_object_before_a_shared_one(catalog, alice, bob, make_ingredient):
    """A component naming "Sauce" when the owner has their own "Sauce" *and* a bystander has a
    public "Sauce" resolves to the owner's own row, not nondeterministically (09 rework, NB A).
    """
    from core.models import Visibility

    alice_sauce = make_ingredient("Sauce", owner=alice)
    make_ingredient("Sauce", owner=bob, visibility=Visibility.PUBLIC)  # also visible to alice
    data = _file(
        ingredients=[],
        recipes=[
            {
                "name": "Pasta",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"ingredient": "Sauce", "quantity": "1", "unit": "g"}],
            }
        ],
        dishes=[],
    )

    _run(data, owner=alice)

    component = Recipe.objects.get(owner=alice, name="Pasta").components.get()
    assert component.ingredient == alice_sauce


def test_unknown_private_reference_is_rejected(catalog, alice, bob, make_ingredient):
    """The mirror: a component naming a private ingredient that is *not* declared in the file
    fails validation rather than silently binding to the other user's row.
    """
    make_ingredient("Saffron", owner=bob)
    data = _file(
        ingredients=[],
        recipes=[
            {
                "name": "Rice",
                "yield_quantity": "1",
                "yield_unit": "cup",
                "components": [{"ingredient": "Saffron", "quantity": "1", "unit": "g"}],
            }
        ],
        dishes=[],
    )

    with pytest.raises(ImportValidationError) as excinfo:
        _run(data, owner=alice)

    assert any("Saffron" in p.message for p in excinfo.value.problems)


def test_management_command_matches_admin_page(catalog, alice, bob, user_factory, tmp_path):
    admin_user = user_factory(username="importadmin", is_staff=True, is_superuser=True)
    payload = _file()
    path = tmp_path / "import.json"
    path.write_text(json.dumps(payload))

    call_command("import_json", str(path), "--owner", alice.username)

    client = Client()
    client.force_login(admin_user)
    with path.open("rb") as handle:
        response = client.post(
            reverse("admin:core_import_json"),
            {"file": handle, "owner": str(bob.pk), "mode": SKIP_EXISTING},
        )
    assert response.status_code == 200

    def snapshot(owner):
        return {
            "ingredients": sorted(
                Ingredient.objects.filter(owner=owner).values_list("name", flat=True)
            ),
            "recipes": sorted(
                (r.name, tuple(c.ingredient.name for c in r.components.all()))
                for r in Recipe.objects.filter(owner=owner)
            ),
            "dishes": sorted(
                (d.name, tuple(c.recipe.name for c in d.components.all()))
                for d in Dish.objects.filter(owner=owner)
            ),
        }

    assert snapshot(alice) == snapshot(bob)
    assert snapshot(alice)["recipes"] == [("Bread", ("Flour",))]
