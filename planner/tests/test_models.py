"""Planner model behaviour (``Plan/08-Meal-Planner/test-plan.md``, "Models")."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core.models import OwnedModel
from planner.models import MealPlan, MealPlanEntry, MealPlanProfile

pytestmark = pytest.mark.django_db


def _profile(owner, **kwargs) -> MealPlanProfile:
    defaults = {"owner": owner, "name": "P"}
    defaults.update(kwargs)
    return MealPlanProfile(**defaults)


def test_profile_days_range(alice):
    for bad in (0, 8):
        with pytest.raises(ValidationError):
            _profile(alice, days=bad).full_clean()

    _profile(alice, days=1).full_clean()
    _profile(alice, days=7).full_clean()


def test_profile_days_range_enforced_in_db(alice):
    with pytest.raises(IntegrityError), transaction.atomic():
        MealPlanProfile.objects.create(owner=alice, name="P", days=9)


def test_profile_slots_not_empty(alice):
    with pytest.raises(ValidationError):
        _profile(alice, slots=[]).full_clean()

    with pytest.raises(ValidationError):
        _profile(alice, slots=["BRUNCH"]).full_clean()

    _profile(alice, slots=["DINNER", "LUNCH"]).full_clean()


def test_min_rating_range(alice):
    for bad in (0, 6):
        with pytest.raises(ValidationError):
            _profile(alice, min_rating=bad).full_clean()

    _profile(alice, min_rating=1).full_clean()
    _profile(alice, min_rating=5).full_clean()
    _profile(alice, min_rating=None).full_clean()


def test_tag_limits_must_be_name_to_count(alice):
    with pytest.raises(ValidationError):
        _profile(alice, tag_limits={"chicken": -1}).full_clean()

    with pytest.raises(ValidationError):
        _profile(alice, tag_limits=["chicken"]).full_clean()

    _profile(alice, tag_limits={"chicken": 1, "beef": 0}).full_clean()


def test_one_default_profile_per_user(alice, bob):
    MealPlanProfile.objects.create(owner=alice, name="Weekday", is_default=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        MealPlanProfile.objects.create(owner=alice, name="Weekend", is_default=True)

    # a non-default second profile is fine, and another user's default is independent
    MealPlanProfile.objects.create(owner=alice, name="Weekend", is_default=False)
    MealPlanProfile.objects.create(owner=bob, name="Mine", is_default=True)


def test_entry_unique_per_day_slot(make_plan):
    plan = make_plan()
    MealPlanEntry.objects.create(plan=plan, day_index=0, slot="DINNER")

    with pytest.raises(IntegrityError), transaction.atomic():
        MealPlanEntry.objects.create(plan=plan, day_index=0, slot="DINNER")

    MealPlanEntry.objects.create(plan=plan, day_index=0, slot="LUNCH")
    MealPlanEntry.objects.create(plan=plan, day_index=1, slot="DINNER")


def test_plan_stores_seed_and_snapshot(make_plan):
    snapshot = {"days": 5, "slots": ["DINNER"], "dish_template": "ONE_POT"}
    plan = make_plan(seed=99887766, profile_snapshot=snapshot, days=5)

    reloaded = MealPlan.objects.get(pk=plan.pk)
    assert reloaded.seed == 99887766
    assert reloaded.profile_snapshot == snapshot


def test_plan_is_owned():
    assert issubclass(MealPlan, OwnedModel)
    assert MealPlan.contains_owned_children is False


def test_entry_dish_set_null_on_delete(make_plan, make_dish, add_component, make_recipe):
    plan = make_plan()
    dish = make_dish("Roast")
    add_component(dish, make_recipe("R"))
    entry = MealPlanEntry.objects.create(plan=plan, day_index=0, slot="DINNER", dish=dish)

    dish.delete()

    entry.refresh_from_db()
    assert entry.dish_id is None
    assert MealPlanEntry.objects.filter(pk=entry.pk).exists()


def test_deleting_profile_keeps_plan_via_set_null(make_plan, make_profile):
    profile = make_profile()
    plan = make_plan(profile=profile, profile_snapshot={"days": 7})

    profile.delete()

    plan.refresh_from_db()
    assert plan.profile_id is None
    assert plan.profile_snapshot == {"days": 7}


def test_plan_start_date_required(alice):
    plan = MealPlan(owner=alice, days=7, seed=1)
    with pytest.raises(ValidationError):
        plan.full_clean()


def test_entry_ordering(make_plan):
    plan = make_plan()
    MealPlanEntry.objects.create(plan=plan, day_index=1, slot="DINNER")
    MealPlanEntry.objects.create(plan=plan, day_index=0, slot="LUNCH")
    MealPlanEntry.objects.create(plan=plan, day_index=0, slot="DINNER")

    ordered = [(entry.day_index, entry.slot) for entry in plan.entries.all()]
    assert ordered == [(0, "DINNER"), (0, "LUNCH"), (1, "DINNER")]


def test_profile_default_slots_is_dinner(alice):
    profile = MealPlanProfile.objects.create(owner=alice, name="P")
    assert profile.slots == ["DINNER"]


def test_profile_favorites_bias_default(alice):
    from decimal import Decimal

    profile = MealPlanProfile.objects.create(owner=alice, name="P")
    profile.refresh_from_db()
    assert profile.favorites_bias == Decimal("1.50")


def test_start_date_default_only_used_for_backfill(make_plan):
    plan = make_plan(start_date=datetime.date(2026, 3, 2))
    assert plan.start_date == datetime.date(2026, 3, 2)
