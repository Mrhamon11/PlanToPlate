"""DRF serializers for the lists API (``Plan/07-Lists-And-Shopping/design.md``, "API").

``List`` is an ``OwnedModel``, so ``ListSerializer`` extends ``core.serializers.OwnedSerializer``
and inherits the read-only ``owner`` / ``visibility`` / ``shared_with`` / ``is_system`` /
``copied_from`` guard and the ``owner``-from-``request.user`` injection on create.

Two security rules the design turns on (design.md, "Security notes"):

1. **Every content FK on an item is validated as visible to the actor on write.** ``recipe`` /
   ``dish`` / ``ingredient`` are scoped to ``visible_to(request.user)``, so attaching a guessed
   id fails identically to a nonexistent one — no reading someone else's recipe back through
   your own list.
2. **Counts and previews never leak invisible content on read.** A shared list whose item
   points at a recipe the recipient cannot see renders that item's name as ``null``
   (a tombstone), resolved for the whole page in three queries.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import serializers

from catalog.models import Ingredient, Unit
from core.serializers import OwnedSerializer
from lists.models import List, ListItem
from meals.models import Dish
from recipes.models import Recipe

#: Above this many items a list response truncates its embedded ``items`` and sets
#: ``items_truncated`` (design.md, "Edge cases": "paginate above ~200 items"). The full set is
#: available page by page from ``GET /api/lists/<id>/items/``.
MAX_EMBEDDED_ITEMS = 200


def visible_item_target_caches(items: Any, user: Any) -> dict[str, set[Any]]:
    """The ids of every recipe / dish / ingredient referenced by ``items`` that ``user`` can
    actually see — three queries total, regardless of how many items.

    Returned as a dict ready to merge into a serializer context; ``ListItemSerializer`` reads
    the three keys to decide whether to show a reference's name or ``null`` it as a tombstone.
    """
    recipe_ids: set[Any] = set()
    dish_ids: set[Any] = set()
    ingredient_ids: set[Any] = set()
    for item in items:
        if item.recipe_id:
            recipe_ids.add(item.recipe_id)
        if item.dish_id:
            dish_ids.add(item.dish_id)
        if item.ingredient_id:
            ingredient_ids.add(item.ingredient_id)
    return {
        "_visible_recipe_ids": set(
            Recipe.objects.visible_to(user).filter(pk__in=recipe_ids).values_list("pk", flat=True)
        ),
        "_visible_dish_ids": set(
            Dish.objects.visible_to(user).filter(pk__in=dish_ids).values_list("pk", flat=True)
        ),
        "_visible_ingredient_ids": set(
            Ingredient.objects.visible_to(user)
            .filter(pk__in=ingredient_ids)
            .values_list("pk", flat=True)
        ),
    }


class ListItemSerializer(serializers.ModelSerializer):
    """One line of a list. ``recipe`` / ``dish`` / ``ingredient`` are plain primary-key fields
    whose queryset is scoped to what the requester can see (in ``__init__``, which only the
    single-instance write path reaches with a request in context). ``*_name`` are read-only
    display helpers that return ``null`` when the related row is not visible to the viewer —
    the documented graceful degradation, never the full row.
    """

    recipe = serializers.PrimaryKeyRelatedField(
        queryset=Recipe.objects.none(), required=False, allow_null=True
    )
    dish = serializers.PrimaryKeyRelatedField(
        queryset=Dish.objects.none(), required=False, allow_null=True
    )
    ingredient = serializers.PrimaryKeyRelatedField(
        queryset=Ingredient.objects.none(), required=False, allow_null=True
    )
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(), required=False, allow_null=True
    )
    recipe_name = serializers.SerializerMethodField()
    dish_name = serializers.SerializerMethodField()
    ingredient_name = serializers.SerializerMethodField()

    class Meta:
        model = ListItem
        fields = [
            "id",
            "position",
            "is_checked",
            "text",
            "recipe",
            "recipe_name",
            "dish",
            "dish_name",
            "ingredient",
            "ingredient_name",
            "quantity",
            "unit",
            "source",
            "generated_from",
        ]
        read_only_fields = ["source", "generated_from"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            user = getattr(request, "user", None)
            self.fields["recipe"].queryset = Recipe.objects.visible_to(user)
            self.fields["dish"].queryset = Dish.objects.visible_to(user)
            self.fields["ingredient"].queryset = Ingredient.objects.visible_to(user)

    def _name_if_visible(self, obj_id: Any, related: Any, cache_key: str) -> str | None:
        if not obj_id:
            return None
        visible = self.context.get(cache_key)
        if visible is not None and obj_id not in visible:
            return None
        return related.name if related is not None else None

    def get_recipe_name(self, obj: ListItem) -> str | None:
        return self._name_if_visible(obj.recipe_id, obj.recipe, "_visible_recipe_ids")

    def get_dish_name(self, obj: ListItem) -> str | None:
        return self._name_if_visible(obj.dish_id, obj.dish, "_visible_dish_ids")

    def get_ingredient_name(self, obj: ListItem) -> str | None:
        return self._name_if_visible(obj.ingredient_id, obj.ingredient, "_visible_ingredient_ids")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        def effective(name: str) -> Any:
            if name in attrs:
                return attrs[name]
            return getattr(self.instance, name, None) if self.instance is not None else None

        recipe = effective("recipe")
        dish = effective("dish")
        ingredient = effective("ingredient")

        has_content = (
            bool((effective("text") or "").strip())
            or recipe is not None
            or dish is not None
            or ingredient is not None
        )
        if not has_content:
            raise serializers.ValidationError(
                "An item needs text, a recipe, a dish, or an ingredient."
            )

        # Exactly one content FK. The ``ListItem`` docstring already says "exactly one of…" and
        # every service produces single-FK items; without this guard a two-FK item slips past the
        # ``pre_delete`` tombstone receivers (each skips the item because another FK is still
        # set) and then violates ``lists_listitem_has_content`` when both null in one cascade
        # (CO-1 / 07.1 review).
        set_fks = [fk for fk in (recipe, dish, ingredient) if fk is not None]
        if len(set_fks) > 1:
            raise serializers.ValidationError(
                "An item can reference only one of a recipe, a dish, or an ingredient."
            )

        # A unit with no quantity says nothing on a list — the same rule
        # ``lists.services.update_item`` enforces for the HTML inline edit (07.23). Only a
        # request that *explicitly* sets a unit is rejected: a PATCH that just clears
        # ``quantity`` is a valid "make this a bare line" edit, and ``update()`` clears the
        # unit with it.
        if attrs.get("unit") is not None and effective("quantity") is None:
            raise serializers.ValidationError(
                "Choose a quantity before setting a unit, or clear both."
            )
        return attrs

    def update(self, instance: ListItem, validated_data: dict[str, Any]) -> ListItem:
        """``quantity`` / ``unit`` are written by ``lists.services.update_item`` — the one
        function the HTML inline edit (07.23) also calls, so "a unit needs a quantity" and
        "an edit never changes ``source``" live in a single place (ARCHITECTURE.md, section 6).
        Every other field (``is_checked``, ``text``, ``position``, the content FKs) is the
        plain assignment ``ModelSerializer`` already does.
        """
        from lists.services import update_item

        has_quantity = "quantity" in validated_data
        has_unit = "unit" in validated_data
        quantity = validated_data.pop("quantity", None)
        unit = validated_data.pop("unit", None)

        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if has_quantity or has_unit:
                new_quantity = quantity if has_quantity else instance.quantity
                if has_unit:
                    new_unit = unit
                elif new_quantity is None:
                    new_unit = None
                else:
                    new_unit = instance.unit
                update_item(instance, quantity=new_quantity, unit=new_unit)
        return instance


class ListSerializer(OwnedSerializer):
    """A list and (up to ``MAX_EMBEDDED_ITEMS`` of) its items.

    ``is_default_shopping_list`` is read-only: it is set only by
    ``lists.services.get_or_create_default_shopping_list``, never a client field.
    """

    items = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    checked_count = serializers.SerializerMethodField()
    items_truncated = serializers.SerializerMethodField()

    class Meta:
        model = List
        fields = [
            "id",
            "name",
            "kind",
            "is_default_shopping_list",
            "items",
            "item_count",
            "checked_count",
            "items_truncated",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_default_shopping_list", "created_at", "updated_at"]

    def _user(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "user", None)

    def _ensure_visibility_caches(self, obj: List) -> None:
        """Resolve, once for the whole page, which of the items' recipe / dish / ingredient
        references the requester can actually see — three queries total, not one ``visible_to``
        per item (mirrors ``meals.serializers``' page-wide resolution).
        """
        if "_visible_recipe_ids" in self.context:
            return
        siblings = self.parent.instance if self.parent is not None else None
        lists = list(siblings) if siblings is not None else [obj]
        items = [item for lst in lists for item in lst.items.all()]
        self.context.update(visible_item_target_caches(items, self._user()))

    def get_items(self, obj: List) -> list[dict[str, Any]]:
        self._ensure_visibility_caches(obj)
        items = list(obj.items.all())[:MAX_EMBEDDED_ITEMS]
        return ListItemSerializer(items, many=True, context=self.context).data

    def get_item_count(self, obj: List) -> int:
        return len(obj.items.all())

    def get_checked_count(self, obj: List) -> int:
        return sum(1 for item in obj.items.all() if item.is_checked)

    def get_items_truncated(self, obj: List) -> bool:
        return len(obj.items.all()) > MAX_EMBEDDED_ITEMS


class ShoppingResultSerializer(serializers.Serializer):
    """The summary ``lists.services.populate_shopping_list`` returns — what a regeneration did,
    so the UI can report it instead of silently mutating the list.
    """

    added = serializers.IntegerField(read_only=True)
    replaced = serializers.IntegerField(read_only=True)
    staples_skipped = serializers.IntegerField(read_only=True)
    items = ListItemSerializer(many=True, read_only=True)


class ReorderSerializer(serializers.Serializer):
    """Body for ``PATCH /api/lists/<id>/reorder/`` — the item ids in their new order."""

    item_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class AddDishSerializer(serializers.Serializer):
    """Body for ``POST /api/lists/<id>/add-dish/``. ``dish``'s queryset is scoped to what the
    requester can see, so an invisible id reads as "does not exist".
    """

    dish = serializers.PrimaryKeyRelatedField(queryset=Dish.objects.none())
    exclude_staples = serializers.BooleanField(required=False, default=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None:
            self.fields["dish"].queryset = Dish.objects.visible_to(getattr(request, "user", None))
