"""DRF serializers for the meal-planner API (``Plan/08-Meal-Planner/design.md``, "API").

Three security rules the design turns on here:

1. **A profile is private to its owner.** ``MealPlanProfileViewSet`` scopes every queryset to
   ``owner=request.user``; this serializer only ever injects ``owner`` from the request.
2. **A plan never surfaces a dish the viewer cannot see.** ``MealPlanEntrySerializer`` filters
   every entry's ``dish`` through ``Dish.objects.visible_to(request.user)`` on write, and
   tombstones the name to ``null`` on read. Sharing a plan *cascades* read to its scheduled
   dishes (D44 re-decision, 08.20), so a freshly shared plan's recipient can see every dish —
   but this tombstone still matters when a dish is unshared after the plan was, or the plan's
   ``shared_with`` was edited directly.
3. **``shopping_list`` is constrained to lists the requester owns.** Otherwise linking a
   victim's list id and regenerating would populate their list
   (``lists.services.generate_shopping_list`` checks visibility against ``lst.owner``).

``profile_snapshot`` and ``seed`` are server-generated and read-only — a client cannot inject
either (``design.md``, "Security notes"). ``profile_snapshot`` is additionally **owner-only on
read**: it embeds the owner's allergy list, so a shared or ``PUBLIC`` plan returns ``{}`` for
it to anyone but the owner (D35 pattern, same as ``OwnedSerializer.shared_with``).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from catalog.models import Ingredient, Tag
from core.serializers import OwnedSerializer
from lists.models import List
from meals.models import Dish
from planner.models import (
    MAX_DAYS,
    MealPlan,
    MealPlanEntry,
    MealPlanProfile,
    MealSlot,
    validate_slots,
    validate_tag_limits,
)
from planner.services.persist import snapshot_slots
from recipes.serializers import FlatLineSerializer

#: ``MealPlan.seed`` is a signed 64-bit ``BigIntegerField``; the generator only needs a
#: non-negative int, so the API accepts ``0 .. 2**63 - 1`` and rejects anything else
#: (``design.md``, "Security notes": "The seed is an integer, validated and bounded").
SEED_MIN = 0
SEED_MAX = 2**63 - 1


def _seed_field(**kwargs: Any) -> serializers.IntegerField:
    return serializers.IntegerField(min_value=SEED_MIN, max_value=SEED_MAX, **kwargs)


class MealPlanProfileSerializer(serializers.ModelSerializer):
    """The eight gears (plus ``exclude_staples``) as a saved, named profile.

    ``slots`` is validated non-empty here because — unlike ``days`` and ``min_rating`` — no DB
    ``CheckConstraint`` backs it, only the model ``clean()`` the ORM ``create()`` path skips
    (08.9 carried finding). ``excluded_ingredients`` is scoped to what the requester can see.
    """

    excluded_tags = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Tag.objects.all(), required=False
    )
    excluded_ingredients = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Ingredient.objects.none(), required=False
    )

    class Meta:
        model = MealPlanProfile
        fields = [
            "id",
            "name",
            "is_default",
            "days",
            "slots",
            "dish_template",
            "source_scope",
            "tag_limits",
            "excluded_tags",
            "excluded_ingredients",
            "no_repeat_days",
            "min_rating",
            "favorites_only",
            "favorites_bias",
            "max_total_minutes",
            "exclude_staples",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            user = getattr(request, "user", None)
            self.fields[
                "excluded_ingredients"
            ].child_relation.queryset = Ingredient.objects.visible_to(user)

    def validate_slots(self, value: Any) -> list[str]:
        try:
            validate_slots(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return list(value)

    def validate_tag_limits(self, value: Any) -> dict:
        try:
            validate_tag_limits(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def _clear_other_defaults(self, owner: Any, instance: MealPlanProfile | None) -> None:
        """One default per owner is a partial unique constraint — setting a new default has to
        clear the old one first or the write 500s on ``IntegrityError``.
        """
        others = MealPlanProfile.objects.filter(owner=owner, is_default=True)
        if instance is not None:
            others = others.exclude(pk=instance.pk)
        others.update(is_default=False)

    def create(self, validated_data: dict[str, Any]) -> MealPlanProfile:
        owner = self.context["request"].user
        if validated_data.get("is_default"):
            self._clear_other_defaults(owner, None)
        validated_data["owner"] = owner
        return super().create(validated_data)

    def update(self, instance: MealPlanProfile, validated_data: dict[str, Any]) -> MealPlanProfile:
        if validated_data.get("is_default"):
            self._clear_other_defaults(instance.owner, instance)
        return super().update(instance, validated_data)


class MealPlanEntrySerializer(serializers.ModelSerializer):
    """One day/slot cell. ``dish`` is a primary-key field scoped to ``visible_to`` the
    requester (set in ``__init__``, which the single-instance write path reaches with a
    request in context); ``dish_name`` is a read-only helper that returns ``null`` when the
    dish is not visible to the viewer — the documented graceful degradation, never the row.

    ``day_index`` / ``slot`` are read-only: an entry is created by the generator, and edited
    only by swap / lock / clear (``design.md``, "API").
    """

    dish = serializers.PrimaryKeyRelatedField(
        queryset=Dish.objects.none(), required=False, allow_null=True
    )
    dish_name = serializers.SerializerMethodField()
    is_auto_composed = serializers.SerializerMethodField()

    class Meta:
        model = MealPlanEntry
        fields = [
            "id",
            "day_index",
            "slot",
            "dish",
            "dish_name",
            "is_auto_composed",
            "is_locked",
            "note",
        ]
        read_only_fields = ["day_index", "slot"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["dish"].queryset = Dish.objects.visible_to(getattr(request, "user", None))

    def _visible_dish_ids(self) -> set[Any] | None:
        return self.context.get("_visible_dish_ids")

    @staticmethod
    def get_is_auto_composed(obj: MealPlanEntry) -> bool:
        """True for a preview slot the generator filled by composing a transient protein + carb
        + vegetable dish — the grid marks it and offers the "save as a real Dish" path (saving
        the plan persists it). A saved plan's entries always point to real ``Dish`` rows.
        """
        from planner.services.compose import is_composed

        return obj.dish is not None and is_composed(obj.dish)

    def update(
        self, instance: MealPlanEntry, validated_data: dict[str, Any]
    ) -> MealPlanEntry:
        """A manual dish swap is a deliberate override, so it clears ``is_locked`` — the same
        behaviour as the HTML ``PlanEntrySwapView`` (owner decision, 08 final rework). Only a
        PATCH that actually changes ``dish`` touches the lock; one that sets ``is_locked``
        explicitly, or only edits ``note``, leaves it alone.
        """
        dish_changed = "dish" in validated_data and validated_data["dish"] != instance.dish
        if dish_changed and "is_locked" not in validated_data:
            validated_data["is_locked"] = False
        return super().update(instance, validated_data)

    def get_dish_name(self, obj: MealPlanEntry) -> str | None:
        if obj.dish is not None and obj.dish.pk is None:
            # A transient, generator-composed dish ("Roast Chicken + Rice + Green Beans") in a
            # preview — its name is built from the requester's own visible recipes, so it is
            # always safe to show. It has no pk to visibility-check.
            return obj.dish.name
        if not obj.dish_id:
            return None
        visible = self._visible_dish_ids()
        if visible is not None:
            return obj.dish.name if obj.dish_id in visible else None
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if Dish.objects.visible_to(user).filter(pk=obj.dish_id).exists():
            return obj.dish.name
        return None


class MealPlanSerializer(OwnedSerializer):
    """A saved plan and its entries.

    ``profile`` / ``profile_snapshot`` / ``seed`` are read-only: a plan is created by persisting
    a preview (``MealPlanViewSet.create``), never by deserialising these. ``shopping_list`` is
    writable but constrained to lists the requester owns (08.10 carried finding).
    """

    profile = serializers.PrimaryKeyRelatedField(read_only=True)
    #: Owner-only on read: the snapshot carries the owner's ``excluded_ingredients`` — their
    #: allergy list (ARCHITECTURE §5 gear 5) — plus ``excluded_tags``, ``tag_limits`` and the
    #: profile name, none of which a sharee or a viewer of a ``PUBLIC`` plan may see. Same D35
    #: pattern as ``OwnedSerializer.shared_with``.
    profile_snapshot = serializers.SerializerMethodField()
    #: Bounded 1..MAX_DAYS at the boundary — the model field alone is a bare
    #: ``PositiveSmallIntegerField`` and a ``PATCH {"days": 32767}`` would otherwise reconcile
    #: tens of thousands of unfilled entry rows in one transaction (reviewer finding 2).
    days = serializers.IntegerField(min_value=1, max_value=MAX_DAYS)
    shopping_list = serializers.PrimaryKeyRelatedField(
        queryset=List.objects.none(), required=False, allow_null=True
    )
    entries = serializers.SerializerMethodField()

    class Meta:
        model = MealPlan
        fields = [
            "id",
            "name",
            "start_date",
            "days",
            "profile",
            "profile_snapshot",
            "seed",
            "shopping_list",
            "entries",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["seed", "created_at", "updated_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["shopping_list"].queryset = List.objects.filter(
                owner=getattr(request, "user", None)
            )

    @extend_schema_field(serializers.DictField())
    def get_profile_snapshot(self, obj: MealPlan) -> dict:
        """The frozen gear snapshot, but only to the plan's owner — ``{}`` for a sharee or any
        viewer of a ``PUBLIC`` plan. See the field declaration and ARCHITECTURE.md D35.
        """
        request = self.context.get("request")
        user_id = getattr(getattr(request, "user", None), "id", None)
        if user_id is not None and user_id == obj.owner_id:
            return obj.profile_snapshot or {}
        return {}

    def _entry_context(self, obj: MealPlan) -> dict:
        context = dict(self.context)
        dish_ids = {entry.dish_id for entry in obj.entries.all() if entry.dish_id}
        context["_visible_dish_ids"] = set(
            Dish.objects.visible_to(self._user())
            .filter(pk__in=dish_ids)
            .values_list("pk", flat=True)
        )
        return context

    def _user(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_entries(self, obj: MealPlan) -> list[dict[str, Any]]:
        entries = sorted(obj.entries.all(), key=lambda e: (e.day_index, _slot_order(e.slot)))
        return MealPlanEntrySerializer(entries, many=True, context=self._entry_context(obj)).data

    def update(self, instance: MealPlan, validated_data: dict[str, Any]) -> MealPlan:
        days_changed = "days" in validated_data and validated_data["days"] != instance.days
        instance = super().update(instance, validated_data)
        if days_changed:
            from planner.services.persist import reconcile_entries

            reconcile_entries(instance, days=instance.days, slots=snapshot_slots(instance))
        return instance


class PlanResultSerializer(serializers.Serializer):
    """A generation / regeneration preview — the unsaved ``PlanResult`` dataclass."""

    entries = serializers.SerializerMethodField()
    unfilled = serializers.SerializerMethodField()
    seed = serializers.IntegerField(read_only=True)

    def get_entries(self, obj: Any) -> list[dict[str, Any]]:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        entries = sorted(obj.entries, key=lambda e: (e.day_index, _slot_order(e.slot)))
        dish_ids = {e.dish_id for e in entries if getattr(e, "dish_id", None)}
        context = dict(self.context)
        context["_visible_dish_ids"] = set(
            Dish.objects.visible_to(user).filter(pk__in=dish_ids).values_list("pk", flat=True)
        )
        return MealPlanEntrySerializer(entries, many=True, context=context).data

    @staticmethod
    def get_unfilled(obj: Any) -> list[dict[str, Any]]:
        # ``_build_result`` appends to ``unfilled`` and ``reasons`` in lockstep, so a length
        # mismatch is a generator bug — surface it here rather than silently dropping slots.
        return [
            {"day_index": day, "slot": slot, "reason": reason}
            for (day, slot), reason in zip(obj.unfilled, obj.reasons, strict=True)
        ]


class ShoppingPreviewSerializer(serializers.Serializer):
    """The ingredient lines ``generate_shopping_list`` would write — nothing is written."""

    lines = FlatLineSerializer(many=True, read_only=True)
    staples_skipped = serializers.IntegerField(read_only=True)


class GeneratePreviewSerializer(serializers.Serializer):
    """Body for ``POST /api/planner/plans/generate/`` — ``{profile, start_date, seed?}``.

    ``profile``'s queryset is scoped to the requester's own profiles, so another user's
    profile id reads as "does not exist" and ``profile.owner == request.user`` holds for every
    generate / persist / regenerate path (08.10 carried finding).
    """

    profile = serializers.PrimaryKeyRelatedField(queryset=MealPlanProfile.objects.none())
    start_date = serializers.DateField()
    seed = _seed_field(required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["profile"].queryset = MealPlanProfile.objects.filter(
                owner=getattr(request, "user", None)
            )


class PersistPlanSerializer(GeneratePreviewSerializer):
    """Body for ``POST /api/planner/plans/`` — persist a previewed plan. ``days`` is passed
    explicitly so a profile edited between preview and save does not silently change the
    saved plan's length (``design.md``, "Edge cases": "days changed after generation").
    """

    name = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    days = serializers.IntegerField(required=False, min_value=1, max_value=MAX_DAYS)


class RegeneratePlanSerializer(serializers.Serializer):
    """Body for ``POST /api/planner/plans/<id>/regenerate/`` — an optional new seed."""

    seed = _seed_field(required=False)


class RerollEntrySerializer(serializers.Serializer):
    """Body for ``POST /api/planner/plans/<id>/entries/<entry_id>/reroll/``."""

    seed = _seed_field(required=False)


class ShoppingListActionSerializer(serializers.Serializer):
    """Body for the shopping-list generate / preview actions — an optional staples override
    (defaults to the plan's profile / snapshot preference).
    """

    exclude_staples = serializers.BooleanField(required=False, allow_null=True, default=None)


_SLOT_ORDER = {slot: index for index, slot in enumerate(MealSlot.values)}


def _slot_order(slot: str) -> int:
    """Chronological meal order (breakfast, lunch, dinner) — the model default sorts slots
    alphabetically, which the API must not inherit (08.12 carried finding, applied here too).
    """
    return _SLOT_ORDER.get(slot, len(_SLOT_ORDER))


__all__ = [
    "GeneratePreviewSerializer",
    "MealPlanEntrySerializer",
    "MealPlanProfileSerializer",
    "MealPlanSerializer",
    "PersistPlanSerializer",
    "PlanResultSerializer",
    "RegeneratePlanSerializer",
    "RerollEntrySerializer",
    "ShoppingListActionSerializer",
]
