"""Fixtures shared by core's ownership/visibility/permission/graph tests.

Standard cast, per Plan/03-Ownership-And-Sharing/test-plan.md: ``alice`` (owner), ``bob``
(shared-with), ``carol`` (unrelated), ``admin`` (superuser — included because "even a
superuser cannot get a system object through editable_by").
"""

from __future__ import annotations

import datetime as _datetime
from decimal import Decimal as _Decimal

import pytest

from core.models import Visibility
from core.tests.models import (
    DummyComponent,
    DummyContainer,
    DummyDivergentNode,
    DummyJoinedComponent,
    DummyJoinedContainer,
    DummyJoinedLeaf,
    DummyNode,
    DummyOwned,
)


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def bob(user_factory):
    return user_factory(username="bob")


@pytest.fixture
def carol(user_factory):
    return user_factory(username="carol")


@pytest.fixture
def admin(user_factory):
    return user_factory(username="admin", is_staff=True, is_superuser=True)


@pytest.fixture
def make_dummy(db):
    """Factory fixture: build a persisted ``DummyOwned`` with sane defaults, overridable."""

    def _make(**kwargs) -> DummyOwned:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyOwned.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_node(db):
    """Factory fixture: build a persisted ``DummyNode``, for the dependency-graph tests."""

    def _make(**kwargs) -> DummyNode:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyNode.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_divergent_node(db):
    """Factory fixture: build a persisted ``DummyDivergentNode``, whose ``share_edges`` and
    ``copy_edges`` are independent relations — for tests proving the copy service's guard
    applies to the graph it actually copies, not the sharing graph.
    """

    def _make(**kwargs) -> DummyDivergentNode:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyDivergentNode.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_container(db):
    """Factory fixture: build a persisted ``DummyContainer``, whose children are reached only
    through the reverse side of ``DummyComponent`` (the real task-05+ container shape).
    """

    def _make(**kwargs) -> DummyContainer:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyContainer.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_component(db):
    """Factory fixture: build a persisted ``DummyComponent`` linking a ``DummyContainer`` to a
    child ``DummyContainer`` through the plain, non-owned join model.
    """

    def _make(**kwargs) -> DummyComponent:
        return DummyComponent.objects.create(**kwargs)

    return _make


@pytest.fixture
def make_dummy_joined_container(db):
    """Factory fixture: build a persisted ``DummyJoinedContainer`` — the real container half of
    the two-parent join model shape (``RecipeComponent.recipe``/``.ingredient``).
    """

    def _make(**kwargs) -> DummyJoinedContainer:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyJoinedContainer.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_joined_leaf(db):
    """Factory fixture: build a persisted ``DummyJoinedLeaf`` — the genuine-leaf half of the
    same two-parent join model shape, reached only through the join model's *other* FK.
    """

    def _make(**kwargs) -> DummyJoinedLeaf:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyJoinedLeaf.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_joined_component(db):
    """Factory fixture: build a persisted ``DummyJoinedComponent`` linking a
    ``DummyJoinedContainer`` to a ``DummyJoinedLeaf`` through the plain, non-owned,
    two-parent join model.
    """

    def _make(**kwargs) -> DummyJoinedComponent:
        return DummyJoinedComponent.objects.create(**kwargs)

    return _make


# --- real-domain fixtures for the task 12 dashboard / recently-viewed suites ----------------
#
# ``core`` has no models of its own, but ``core.services.dashboard`` / ``.recent`` fan out
# across every app, so these tests need real Recipe / Dish / RecipeBook / List / MealPlan
# rows. Mirrors the per-app conftests (recipes/, meals/, lists/, planner/).

_UNIT_SPECS = {
    "gram": ("grams", "g", "MASS", "1", ""),
    "cup": ("cups", "cup", "VOLUME", "236.5882365", ""),
    "each": ("each", "ea", "COUNT", "1", "generic"),
}


@pytest.fixture
def make_unit(db):
    from catalog.models import Unit

    def _make(name: str) -> Unit:
        plural, abbrev, dimension, factor, family = _UNIT_SPECS[name]
        unit, _ = Unit.objects.get_or_create(
            name=name,
            defaults={
                "plural": plural,
                "abbrev": abbrev,
                "dimension": dimension,
                "to_base_factor": _Decimal(factor),
                "count_family": family,
            },
        )
        return unit

    return _make


@pytest.fixture
def gram(make_unit):
    return make_unit("gram")


@pytest.fixture
def cup(make_unit):
    return make_unit("cup")


@pytest.fixture
def make_tag(db):
    from catalog.models import Tag

    def _make(name: str) -> Tag:
        tag, _ = Tag.objects.get_or_create(name=name)
        return tag

    return _make


@pytest.fixture
def make_ingredient(db, gram):
    from catalog.models import Ingredient

    def _make(name: str = "Tomato", *, owner=None, is_staple: bool = False, **kwargs):
        defaults = {
            "name": name,
            "default_unit": kwargs.pop("default_unit", gram),
            "is_system": owner is None,
            "owner": owner,
            "visibility": Visibility.PRIVATE,
            "is_staple": is_staple,
        }
        defaults.update(kwargs)
        ingredient = Ingredient(**defaults)
        ingredient.save()
        return ingredient

    return _make


@pytest.fixture
def make_recipe(db, alice, cup):
    from recipes.models import Recipe

    def _make(name: str = "Recipe", *, owner=None, **kwargs):
        defaults = {
            "name": name,
            "instructions": "Cook it.",
            "yield_quantity": _Decimal("4.000"),
            "yield_unit": kwargs.pop("yield_unit", cup),
            "owner": owner or alice,
        }
        defaults.update(kwargs)
        recipe = Recipe(**defaults)
        recipe.save()
        return recipe

    return _make


@pytest.fixture
def add_ingredient(db, gram):
    from recipes.models import RecipeComponent

    def _add(recipe, ingredient, quantity="100", unit=None, *, position=0):
        return RecipeComponent.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity=_Decimal(str(quantity)),
            unit=unit or gram,
            position=position,
        )

    return _add


@pytest.fixture
def make_dish(db, alice):
    from meals.models import Dish

    def _make(name: str = "Dish", *, owner=None, **kwargs):
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        dish = Dish(**defaults)
        dish.save()
        return dish

    return _make


@pytest.fixture
def add_component(db):
    from meals.models import DishComponent

    def _add(dish, recipe, *, servings="1", position=0):
        return DishComponent.objects.create(
            dish=dish, recipe=recipe, servings=_Decimal(str(servings)), position=position
        )

    return _add


@pytest.fixture
def dish_with_component(make_dish, make_recipe, add_component):
    """A dish that owns one component recipe — the shape the "what should I make?" panel keeps
    and the planner uses.
    """

    def _make(name: str = "Dinner", *, owner=None):
        dish = make_dish(name, owner=owner)
        add_component(dish, make_recipe(f"{name} recipe", owner=owner or dish.owner))
        return dish

    return _make


@pytest.fixture
def make_book(db, alice):
    from meals.models import RecipeBook

    def _make(name: str = "Book", *, owner=None, **kwargs):
        defaults = {"name": name, "owner": owner or alice}
        defaults.update(kwargs)
        book = RecipeBook(**defaults)
        book.save()
        return book

    return _make


@pytest.fixture
def make_list(db, alice):
    from lists.models import List, ListKind

    def _make(name: str = "List", *, owner=None, kind=ListKind.GENERIC, **kwargs):
        defaults = {"name": name, "owner": owner or alice, "kind": kind}
        defaults.update(kwargs)
        lst = List(**defaults)
        lst.save()
        return lst

    return _make


@pytest.fixture
def make_plan(db, alice):
    from planner.models import MealPlan

    def _make(*, owner=None, start_date=None, days=7, **kwargs):
        defaults = {
            "owner": owner or alice,
            "name": kwargs.pop("name", "This week"),
            "start_date": start_date or _datetime.date(2026, 1, 5),
            "days": days,
            "seed": 1,
            "profile_snapshot": {},
        }
        defaults.update(kwargs)
        return MealPlan.objects.create(**defaults)

    return _make


@pytest.fixture
def add_entry(db):
    from planner.models import MealPlanEntry, MealSlot

    def _add(plan, *, day_index=0, slot=MealSlot.DINNER, dish=None):
        return MealPlanEntry.objects.create(plan=plan, day_index=day_index, slot=slot, dish=dish)

    return _add


@pytest.fixture
def set_favourite(db):
    """Mark ``user``'s ``RecipeStats`` / ``DishStats`` favourite flag for a recipe or dish."""

    from meals.models import Dish, DishStats
    from recipes.models import RecipeStats

    def _set(user, obj, *, is_favorite=True):
        if isinstance(obj, Dish):
            row, _ = DishStats.objects.update_or_create(
                user=user, dish=obj, defaults={"is_favorite": is_favorite}
            )
        else:
            row, _ = RecipeStats.objects.update_or_create(
                user=user, recipe=obj, defaults={"is_favorite": is_favorite}
            )
        return row

    return _set


@pytest.fixture
def share_with(db):
    """Grant ``user`` read access to an owned object (visibility SHARED + ``shared_with``)."""

    from core.models import Visibility as _Visibility

    def _share(obj, user):
        obj.visibility = _Visibility.SHARED
        obj.save(update_fields=["visibility"])
        obj.shared_with.add(user)
        return obj

    return _share
