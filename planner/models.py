"""Meal-planner models (``Plan/08-Meal-Planner/design.md``, "Models").

``MealPlanProfile`` is the saved, named knob set — "the eight gears" (``ARCHITECTURE.md`` §5).
``MealPlan`` / ``MealPlanEntry`` are one generated (or hand-edited) week: a plan carries an
entry per day/slot, each optionally holding a ``Dish``.

``seed`` and ``profile_snapshot`` are what make a plan reproducible and explicable long after
the profile that produced it was edited or deleted (``design.md``, "Why ``seed`` and
``profile_snapshot``").
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from catalog.models import Ingredient, Tag
from core.models import OwnedModel

MAX_DAYS = 7


class MealSlot(models.TextChoices):
    BREAKFAST = "BREAKFAST", "Breakfast"
    LUNCH = "LUNCH", "Lunch"
    DINNER = "DINNER", "Dinner"


class DishTemplate(models.TextChoices):
    BALANCED = "BALANCED", "Balanced (protein, carb, vegetable)"
    ONE_POT = "ONE_POT", "One-pot"
    MIX = "MIX", "Mix it up"


class SourceScope(models.TextChoices):
    MINE = "MINE", "Only my dishes"
    SHARED = "SHARED", "My dishes and dishes shared with me"
    PUBLIC = "PUBLIC", "My dishes, shared, and public dishes"


def default_slots() -> list[str]:
    """Dinner only — the deliberate first-run default (``ARCHITECTURE.md`` §5, gear 1)."""
    return [MealSlot.DINNER.value]


def validate_slots(value: object) -> None:
    """``slots`` must be a non-empty list of known ``MealSlot`` values — an empty slot set is
    a plan with nothing to plan (``tasks.md`` 08.1, ``test_profile_slots_not_empty``).
    """
    if not isinstance(value, list) or not value:
        raise ValidationError("Choose at least one meal slot.", code="slots_empty")
    unknown = [slot for slot in value if slot not in set(MealSlot.values)]
    if unknown:
        raise ValidationError(
            "Unknown meal slot(s): %(slots)s.",
            code="slots_invalid",
            params={"slots": ", ".join(str(slot) for slot in unknown)},
        )


def validate_tag_limits(value: object) -> None:
    """``tag_limits`` is ``{tag name: weekly maximum}`` — a mapping of strings to non-negative
    whole numbers. A limit referencing a tag that does not exist is *not* rejected here; the
    generator simply never matches it (``design.md``, "Edge cases").
    """
    if not isinstance(value, dict):
        raise ValidationError(
            "Tag limits must be a mapping of tag name to a weekly maximum.",
            code="tag_limits_type",
        )
    for key, limit in value.items():
        if (
            not isinstance(key, str)
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 0
        ):
            raise ValidationError(
                "Each tag limit must be a tag name mapped to a non-negative whole number.",
                code="tag_limits_value",
            )


class MealPlanProfile(models.Model):
    """A named, reusable set of the eight generator gears, owned by one user."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="planner_profiles",
    )
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    # gear 1 — when
    days = models.PositiveSmallIntegerField(
        default=MAX_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_DAYS)],
    )
    slots = models.JSONField(default=default_slots, validators=[validate_slots])

    # gear 2 — what
    dish_template = models.CharField(
        max_length=16, choices=DishTemplate.choices, default=DishTemplate.BALANCED
    )
    # gear 3 — scope
    source_scope = models.CharField(
        max_length=16, choices=SourceScope.choices, default=SourceScope.SHARED
    )

    # gear 4 — tag limits
    tag_limits = models.JSONField(default=dict, blank=True, validators=[validate_tag_limits])

    # gear 5 — hard exclusions (allergies)
    excluded_tags = models.ManyToManyField(Tag, related_name="excluded_by", blank=True)
    excluded_ingredients = models.ManyToManyField(
        Ingredient, related_name="excluded_by_profiles", blank=True
    )

    # gear 6 — no repeats
    no_repeat_days = models.PositiveSmallIntegerField(default=14)

    # gear 7 — quality
    min_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    favorites_only = models.BooleanField(default=False)
    favorites_bias = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.5"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    # gear 8 — time budget
    max_total_minutes = models.PositiveIntegerField(null=True, blank=True)

    #: Not one of the eight gears, but a per-profile choice the shopping-list step (08.8) reads
    #: — dropped from the model block in ``design.md`` yet named directly in its shopping-list
    #: snippet (``profile.exclude_staples``). Added here so 08.8 is pure orchestration.
    exclude_staples = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner"],
                condition=Q(is_default=True),
                name="planner_mealplanprofile_one_default_per_owner",
            ),
            models.CheckConstraint(
                condition=Q(days__gte=1, days__lte=MAX_DAYS),
                name="planner_mealplanprofile_days_range",
            ),
            models.CheckConstraint(
                condition=Q(min_rating__isnull=True) | Q(min_rating__gte=1, min_rating__lte=5),
                name="planner_mealplanprofile_min_rating_range",
            ),
            models.CheckConstraint(
                condition=Q(favorites_bias__gte=0),
                name="planner_mealplanprofile_favorites_bias_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        validate_slots(self.slots)
        validate_tag_limits(self.tag_limits)


class MealPlan(OwnedModel):
    """One planned week — generated from a profile, then hand-adjusted."""

    #: **D44 re-decision (task 08).** A ``MealPlan`` *references* owned objects — a ``Dish`` per
    #: entry, an optional ``shopping_list`` — but it does not *contain* them, exactly like
    #: ``lists.List`` (which carries the same ``= False`` for the same reason). Sharing a plan
    #: does not cascade read-grants: a recipient sees only the entries whose dish is already
    #: visible to them, and the generated shopping list is its own separately-shared object.
    #: Copying a plan is out of scope for this task. Declared explicitly because
    #: ``core/tests/test_conventions.py``'s relation-walk reaches ``Dish`` / ``List`` through
    #: ``shopping_list`` and the ``entries`` reverse relation and cannot tell a pointer
    #: collection from a container.
    contains_owned_children = False

    name = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    days = models.PositiveSmallIntegerField()
    profile = models.ForeignKey(
        MealPlanProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans",
    )
    #: The gears exactly as they were at generation time — server-generated, never client
    #: supplied (``design.md``, "Security notes"). Survives editing or deleting the profile.
    profile_snapshot = models.JSONField(default=dict)
    seed = models.BigIntegerField()
    shopping_list = models.ForeignKey(
        "lists.List",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_plans",
    )

    class Meta(OwnedModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"Meal plan #{self.pk}"


class MealPlanEntry(models.Model):
    """One day/slot cell of a plan. ``dish`` is nullable: a slot the generator could not fill,
    or one whose dish was later deleted (``SET_NULL``), shows empty and stays re-rollable
    (``design.md``, "Edge cases").
    """

    plan = models.ForeignKey(MealPlan, on_delete=models.CASCADE, related_name="entries")
    day_index = models.PositiveSmallIntegerField()
    slot = models.CharField(max_length=16, choices=MealSlot.choices)
    dish = models.ForeignKey(
        "meals.Dish",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    #: The user pins the meals they like and regenerates the rest — a locked entry is preserved
    #: across regeneration *and still consumes its tag budget* (``design.md``, "``is_locked``").
    is_locked = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["day_index", "slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "day_index", "slot"],
                name="planner_mealplanentry_unique_day_slot",
            ),
        ]

    def __str__(self) -> str:
        return f"Day {self.day_index} {self.slot}: {self.dish or '—'}"
