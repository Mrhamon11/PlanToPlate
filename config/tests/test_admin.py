"""Every registered changelist renders (task 09.2).

Parametrized over ``admin.site._registry`` so a newly registered ``ModelAdmin`` with a broken
``list_display`` / ``list_select_related` / ``search_fields`` is caught the moment it lands,
not the first time an admin clicks it. Per-model N+1 and search assertions live in the owning
app's ``test_admin.py`` (see ``recipes/tests/test_admin.py``).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

pytestmark = pytest.mark.django_db

_REGISTERED_MODELS = sorted(admin.site._registry, key=lambda m: m._meta.label)


@pytest.fixture
def superadmin(user_factory):
    return user_factory(username="superadmin", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_site_client(client, superadmin):
    client.force_login(superadmin)
    return client


@pytest.mark.parametrize("model", _REGISTERED_MODELS, ids=lambda m: m._meta.label)
def test_changelist_loads_for_each_model(admin_site_client, model):
    opts = model._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")

    response = admin_site_client.get(url)

    assert response.status_code == 200


@pytest.mark.parametrize("model", _REGISTERED_MODELS, ids=lambda m: m._meta.label)
def test_add_form_loads_for_each_model(admin_site_client, superadmin, model):
    """A ``raw_id_fields`` / ``autocomplete_fields`` / inline typo only shows on the change
    form, never the changelist.
    """
    opts = model._meta
    model_admin = admin.site._registry[model]
    request = RequestFactory().get("/")
    request.user = superadmin
    if not model_admin.has_add_permission(request):
        pytest.skip(f"{opts.label} has add disabled")

    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
    # ``accounts.User``'s stock add view redirects to the purpose-built create-user page
    # (09.5); ``follow`` lands on whichever page actually renders the add form.
    response = admin_site_client.get(url, follow=True)

    assert response.status_code == 200


# --- Parametrized changelist N+1 guard (09.1-09.4 review, non-blocking #2) -------------------
#
# ``config`` cannot see a sibling app's ``conftest``, so the row builders needed to scale every
# registered model's changelist from 5 rows to 50 live here. A dropped ``list_select_related``
# on ``lists`` / ``meals`` / ``planner`` (whose per-app ``test_admin.py`` has no query-count
# test) now fails CI instead of only being spot-checked.


class _RowFactory:
    """Builds N rows of any registered model, reusing one shared graph of parent objects so a
    ``list_filter`` dropdown does not itself grow with the row count.
    """

    def __init__(self, user_factory):
        self.user = user_factory(username="rowowner")
        self.other = user_factory(username="rowother")
        from catalog.models import Dimension, Ingredient, Tag, Unit
        from lists.models import List
        from meals.models import Dish, RecipeBook
        from planner.models import MealPlan, MealPlanProfile
        from recipes.models import Recipe

        self.unit = Unit.objects.create(
            name="rowgram",
            abbrev="rg",
            plural="rowgrams",
            dimension=Dimension.MASS,
            to_base_factor=Decimal("1"),
        )
        self.tag = Tag.objects.create(name="rowtag")
        self.ingredient = Ingredient.objects.create(
            name="rowing", default_unit=self.unit, is_system=True
        )
        self.recipe = Recipe.objects.create(
            name="rowrecipe",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=self.unit,
            owner=self.user,
        )
        self.sub_recipe = Recipe.objects.create(
            name="rowsub",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=self.unit,
            owner=self.user,
        )
        self.dish = Dish.objects.create(name="rowdish", owner=self.user)
        self.book = RecipeBook.objects.create(name="rowbook", owner=self.user)
        self.list = List.objects.create(name="rowlist", owner=self.user)
        self.profile = MealPlanProfile.objects.create(name="rowprofile", owner=self.user)
        self.plan = MealPlan.objects.create(
            start_date=datetime.date(2026, 1, 1),
            days=7,
            seed=1,
            owner=self.user,
            profile=self.profile,
        )

    def build(self, model, n, start):
        label = model._meta.label
        builder = getattr(self, f"_build_{label.replace('.', '_').lower()}", None)
        if builder is None:
            pytest.skip(f"no row builder for {label}")
        for i in range(start, start + n):
            builder(i)

    def _build_accounts_user(self, i):
        from accounts.models import User

        User.objects.create(username=f"rowuser{i}")

    def _build_auth_group(self, i):
        from django.contrib.auth.models import Group

        Group.objects.create(name=f"rowgroup{i}")

    def _build_catalog_unit(self, i):
        from catalog.models import Dimension, Unit

        Unit.objects.create(
            name=f"rowunit{i}",
            abbrev=f"ru{i}",
            plural=f"rowunits{i}",
            dimension=Dimension.MASS,
            to_base_factor=Decimal("1"),
        )

    def _build_catalog_tag(self, i):
        from catalog.models import Tag

        Tag.objects.create(name=f"rowtag{i}")

    def _build_catalog_ingredient(self, i):
        from catalog.models import Ingredient

        Ingredient.objects.create(name=f"rowing{i}", default_unit=self.unit, owner=self.user)

    def _build_recipes_recipe(self, i):
        from recipes.models import Recipe

        Recipe.objects.create(
            name=f"rowrec{i}",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=self.unit,
            owner=self.user,
        )

    def _build_recipes_recipecomponent(self, i):
        from recipes.models import RecipeComponent

        RecipeComponent.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity=Decimal("1"),
            unit=self.unit,
            position=i,
        )

    def _build_recipes_recipestats(self, i):
        from recipes.models import Recipe, RecipeStats

        recipe = Recipe.objects.create(
            name=f"rowstatrec{i}",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=self.unit,
            owner=self.user,
        )
        RecipeStats.objects.create(user=self.user, recipe=recipe, rating=3)

    def _build_meals_dish(self, i):
        from meals.models import Dish

        Dish.objects.create(name=f"rowdish{i}", owner=self.user)

    def _build_meals_dishcomponent(self, i):
        from meals.models import DishComponent

        DishComponent.objects.create(
            dish=self.dish, recipe=self.recipe, servings=Decimal("1"), position=i
        )

    def _build_meals_dishstats(self, i):
        from meals.models import Dish, DishStats

        dish = Dish.objects.create(name=f"rowstatdish{i}", owner=self.user)
        DishStats.objects.create(user=self.user, dish=dish, rating=3)

    def _build_meals_recipebook(self, i):
        from meals.models import RecipeBook

        RecipeBook.objects.create(name=f"rowbook{i}", owner=self.user)

    def _build_meals_recipebookentry(self, i):
        from meals.models import RecipeBookEntry
        from recipes.models import Recipe

        recipe = Recipe.objects.create(
            name=f"rowentryrec{i}",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=self.unit,
            owner=self.user,
        )
        RecipeBookEntry.objects.create(book=self.book, recipe=recipe, position=i)

    def _build_lists_list(self, i):
        from lists.models import List

        List.objects.create(name=f"rowlist{i}", owner=self.user)

    def _build_lists_listitem(self, i):
        from lists.models import ListItem

        # Every content FK non-null and shared, so ``ListItemAdmin.list_select_related``
        # is genuinely exercised — with these left null the changelist would touch no
        # related row and dropping ``list_select_related`` would not regress the count.
        ListItem.objects.create(
            list=self.list,
            recipe=self.recipe,
            dish=self.dish,
            ingredient=self.ingredient,
            unit=self.unit,
            quantity=Decimal("1"),
            position=i,
        )

    def _build_planner_mealplan(self, i):
        from planner.models import MealPlan

        MealPlan.objects.create(
            start_date=datetime.date(2026, 1, 1),
            days=7,
            seed=i,
            owner=self.user,
            profile=self.profile,
        )

    def _build_planner_mealplanentry(self, i):
        from planner.models import MealPlan, MealPlanEntry, MealSlot

        plan = MealPlan.objects.create(
            start_date=datetime.date(2026, 1, 1),
            days=7,
            seed=1000 + i,
            owner=self.user,
            profile=self.profile,
        )
        MealPlanEntry.objects.create(plan=plan, day_index=0, slot=MealSlot.DINNER, dish=self.dish)

    def _build_planner_mealplanprofile(self, i):
        from planner.models import MealPlanProfile

        MealPlanProfile.objects.create(name=f"rowprofile{i}", owner=self.user)

    def _build_core_recentview(self, i):
        from core.models import RecentView

        RecentView.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(type(self.recipe)),
            object_id=self.recipe.pk + i + 1,
        )


@pytest.fixture
def row_factory(user_factory):
    return _RowFactory(user_factory)


def _changelist_query_count(client, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200
    return len(ctx.captured_queries)


@pytest.mark.parametrize("model", _REGISTERED_MODELS, ids=lambda m: m._meta.label)
def test_changelist_query_count_bounded(admin_site_client, row_factory, model):
    """A 50-row changelist fires no more queries than a 5-row one — every FK column is covered
    by ``list_select_related`` (``design.md`` 09.2: "no changelist N+1s").
    """
    opts = model._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")

    row_factory.build(model, 5, start=0)
    baseline = _changelist_query_count(admin_site_client, url)

    row_factory.build(model, 45, start=5)
    scaled = _changelist_query_count(admin_site_client, url)

    assert scaled == baseline, f"{opts.label} changelist N+1: {baseline} -> {scaled} queries"
