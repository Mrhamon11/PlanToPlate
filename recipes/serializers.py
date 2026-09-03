"""DRF serializers for the recipes API (``Plan/05-Recipes/design.md``, "API").

``Recipe`` is an ``OwnedModel``, so ``RecipeSerializer`` extends
``core.serializers.OwnedSerializer`` and inherits the read-only
``owner`` / ``visibility`` / ``shared_with`` / ``is_system`` /
``copied_from`` guard and the ``owner``-from-``request.user`` injection on create.

Components are written **nested** on the recipe as replace-the-set semantics inside one
transaction (design.md, "API": "Separate component endpoints would let a client leave a recipe
half-saved"). Two rules are enforced on that write path:

1. **Visibility.** Every referenced ingredient and sub-recipe must be ``visible_to`` the
   requester. Without this a user attaches an object they only guessed the ID of and reads its
   contents back through their own recipe (design.md, "Security notes": "the highest-value IDOR
   test in the task").
2. **The cycle guard.** ``recipes.services.graph.assert_no_cycle`` runs for every sub-recipe
   component — the serializer is one of the three write paths the guard must cover.

On read, a component whose ingredient or sub-recipe is somehow *not* visible to the viewer
degrades to the bare name rather than 500ing or dumping the full related row — defence in depth
for a share-cascade bug (design.md, "Edge cases").
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import serializers

from catalog.exceptions import IncompatibleUnits
from catalog.models import Ingredient
from catalog.services.units import convert
from core.serializers import OwnedSerializer
from recipes.models import Recipe, RecipeComponent, RecipeStats
from recipes.services.graph import GraphError, assert_no_cycle


class RecipeComponentSerializer(serializers.ModelSerializer):
    """One line of a recipe. ``ingredient`` and ``sub_recipe`` are plain primary-key fields;
    their *visibility* is validated by the parent ``RecipeSerializer`` (which has the request
    context and the target recipe), not here — a nested child serializer is not reliably bound
    to its parent's context at ``__init__`` time.

    ``ingredient_name`` / ``sub_recipe_name`` are read-only display helpers that stay safe even
    when the related row is not visible to the viewer: a name is the documented graceful
    degradation, never the full row.
    """

    ingredient_name = serializers.SerializerMethodField()
    sub_recipe_name = serializers.SerializerMethodField()

    class Meta:
        model = RecipeComponent
        fields = [
            "id",
            "ingredient",
            "ingredient_name",
            "sub_recipe",
            "sub_recipe_name",
            "quantity",
            "unit",
            "position",
            "note",
        ]

    def get_ingredient_name(self, obj: RecipeComponent) -> str | None:
        return obj.ingredient.name if obj.ingredient_id else None

    def get_sub_recipe_name(self, obj: RecipeComponent) -> str | None:
        return obj.sub_recipe.name if obj.sub_recipe_id else None


class RecipeSerializer(OwnedSerializer):
    components = RecipeComponentSerializer(many=True, required=False)

    class Meta:
        model = Recipe
        fields = [
            "id",
            "name",
            "description",
            "instructions",
            "yield_quantity",
            "yield_unit",
            "prep_minutes",
            "cook_minutes",
            "role",
            "tags",
            "source_url",
            "components",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _user(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "user", None)

    def validate_components(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reject a component that names neither/both targets, an ingredient or sub-recipe the
        requester cannot see, or a sub-recipe whose yield unit cannot be reconciled with the
        component's unit. The visibility check is the flagship IDOR defence (design.md).
        """
        user = self._user()
        for component in value:
            ingredient = component.get("ingredient")
            sub_recipe = component.get("sub_recipe")

            if (ingredient is None) == (sub_recipe is None):
                raise serializers.ValidationError(
                    "Each component must reference exactly one of an ingredient or a sub-recipe."
                )

            if ingredient is not None and not _is_visible(Ingredient, ingredient, user):
                raise serializers.ValidationError(
                    "One of the components references an ingredient that is not available to you."
                )

            if sub_recipe is not None:
                if self.instance is not None and sub_recipe.pk == self.instance.pk:
                    raise serializers.ValidationError("A recipe cannot contain itself.")
                if not _is_visible(Recipe, sub_recipe, user):
                    raise serializers.ValidationError(
                        "One of the components references a recipe that is not available to you."
                    )
                self._assert_sub_recipe_unit_scalable(component, sub_recipe)
        return value

    @staticmethod
    def _assert_sub_recipe_unit_scalable(component: dict[str, Any], sub_recipe: Recipe) -> None:
        """A sub-recipe component's quantity is scaled by
        ``convert(quantity, component.unit, sub_recipe.yield_unit) / sub_recipe.yield_quantity``
        when the recipe is flattened (``flatten`` step 3). If that conversion is impossible —
        the component's unit and the sub-recipe's yield unit measure different things — the
        recipe can never become a shopping list, so it is refused **here at validation** with a
        clear message rather than accepted and only failing later as a 400 from ``flattened``
        (design.md, "Edge cases": "refuse at validation with a clear message, since the factor
        is uncomputable").
        """
        unit = component.get("unit")
        quantity = component.get("quantity")
        if unit is None or quantity is None:
            return
        try:
            convert(quantity, unit, sub_recipe.yield_unit)
        except IncompatibleUnits as exc:
            raise serializers.ValidationError(
                f"Sub-recipe '{sub_recipe.name}' is called for in {unit.name}, but it yields "
                f"{sub_recipe.yield_unit.name}, and those measure different things — there is "
                "no way to scale it. Use a unit compatible with the sub-recipe's yield."
            ) from exc

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Recipe:
        components_data = validated_data.pop("components", [])
        recipe = super().create(validated_data)
        self._write_components(recipe, components_data)
        return recipe

    @transaction.atomic
    def update(self, instance: Recipe, validated_data: dict[str, Any]) -> Recipe:
        components_data = validated_data.pop("components", None)
        recipe = super().update(instance, validated_data)
        if components_data is not None:
            recipe.components.all().delete()
            self._write_components(recipe, components_data)
        return recipe

    def _write_components(self, recipe: Recipe, components_data: list[dict[str, Any]]) -> None:
        for index, data in enumerate(components_data):
            data = {**data}
            data.setdefault("position", index)
            sub_recipe = data.get("sub_recipe")
            if sub_recipe is not None:
                try:
                    assert_no_cycle(recipe, sub_recipe)
                except GraphError as exc:
                    raise serializers.ValidationError({"components": [str(exc)]}) from exc
            RecipeComponent.objects.create(recipe=recipe, **data)


class RecipeStatsSerializer(serializers.ModelSerializer):
    """The requester's own per-user stats for a recipe. ``times_made`` / ``last_made_at`` move
    only through ``POST /made/``; ``PUT /stats/`` sets ``rating`` and ``is_favorite``.
    """

    class Meta:
        model = RecipeStats
        fields = ["rating", "is_favorite", "times_made", "last_made_at"]
        read_only_fields = ["times_made", "last_made_at"]


class FlatLineSerializer(serializers.Serializer):
    """One aggregated ingredient line from ``recipes.services.flatten`` — a frozen dataclass,
    not a model. ``quantity`` is rendered as a string for the same lossless-decimal reason the
    unit-conversion endpoint is (``catalog/api.py``): DRF's JSON encoder coerces a bare
    ``Decimal`` to ``float``.
    """

    ingredient = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()
    from_recipes = serializers.ListField(child=serializers.CharField())

    def get_ingredient(self, obj: Any) -> dict[str, Any]:
        return {"id": obj.ingredient.pk, "name": obj.ingredient.name}

    def get_quantity(self, obj: Any) -> str:
        return str(obj.quantity)

    def get_unit(self, obj: Any) -> dict[str, Any]:
        return {"id": obj.unit.pk, "name": obj.unit.name, "abbrev": obj.unit.abbrev}


def _is_visible(model: type, instance: Any, user: Any) -> bool:
    return model.objects.visible_to(user).filter(pk=instance.pk).exists()


__all__ = [
    "FlatLineSerializer",
    "RecipeComponentSerializer",
    "RecipeSerializer",
    "RecipeStatsSerializer",
]
