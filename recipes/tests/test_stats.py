"""Per-user stats tests (``Plan/05-Recipes/test-plan.md``, "Stats")."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.services.copying import copy_object
from recipes.models import RecipeStats
from recipes.services import stats as stats_service

pytestmark = pytest.mark.django_db


def test_stats_created_lazily(alice, make_recipe):
    recipe = make_recipe()

    stats = stats_service.get_stats(alice, recipe)

    assert stats.pk is None
    assert stats.rating is None
    assert stats.times_made == 0
    assert not RecipeStats.objects.filter(user=alice, recipe=recipe).exists()


def test_stats_unique_per_user_recipe(alice, make_recipe):
    recipe = make_recipe()
    RecipeStats.objects.create(user=alice, recipe=recipe)

    with pytest.raises(IntegrityError), transaction.atomic():
        RecipeStats.objects.create(user=alice, recipe=recipe)


def test_two_users_independent_stats(alice, bob, make_recipe):
    recipe = make_recipe()

    stats_service.set_rating(alice, recipe, 5)
    stats_service.set_rating(bob, recipe, 2)

    assert RecipeStats.objects.get(user=alice, recipe=recipe).rating == 5
    assert RecipeStats.objects.get(user=bob, recipe=recipe).rating == 2


def test_mark_made_increments_and_stamps(alice, make_recipe):
    recipe = make_recipe()
    before = timezone.now()

    stats_service.mark_made(alice, recipe)
    stats_service.mark_made(alice, recipe)

    row = RecipeStats.objects.get(user=alice, recipe=recipe)
    assert row.times_made == 2
    assert row.last_made_at >= before


def test_rating_out_of_range_rejected(alice, make_recipe):
    recipe = make_recipe()

    for bad in (0, 6):
        with pytest.raises(ValidationError):
            stats_service.set_rating(alice, recipe, bad)

    assert not RecipeStats.objects.filter(user=alice, recipe=recipe).exists()


def test_stats_not_copied_with_recipe(alice, make_recipe):
    recipe = make_recipe(owner=alice)
    stats_service.set_rating(alice, recipe, 5)
    stats_service.mark_made(alice, recipe)

    copy = copy_object(recipe, actor=alice)

    assert not RecipeStats.objects.filter(recipe=copy).exists()


def test_stats_deleted_with_user(alice, make_recipe):
    recipe = make_recipe(owner=alice)
    stats_service.toggle_favorite(alice, recipe)
    assert RecipeStats.objects.filter(recipe=recipe).exists()

    alice.delete()

    assert not RecipeStats.objects.filter(recipe=recipe).exists()
