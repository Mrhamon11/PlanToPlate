"""DRF serializers for the catalog API (``Plan/04-Units-And-Ingredients/design.md``, "API").

``Unit`` and ``Tag`` are shared vocabulary, not owned — plain ``ModelSerializer``s, read-only
for everyone but staff (the viewset gates writes, not the serializer). ``Ingredient`` is an
``OwnedModel``, so its serializer extends ``core.serializers.OwnedSerializer`` and inherits the
read-only ``owner``/``visibility``/``shared_with``/``is_system``/``copied_from`` guard and the
``owner``-from-``request.user`` injection on create (see that module and ``core/README.md``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from catalog.models import Ingredient, Tag, Unit
from catalog.services.ingredients import owner_has_ingredient_named
from core.serializers import OwnedSerializer


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = [
            "id",
            "name",
            "plural",
            "abbrev",
            "dimension",
            "to_base_factor",
            "count_family",
            "is_system",
        ]


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "kind", "slug"]
        read_only_fields = ["slug"]


class IngredientSerializer(OwnedSerializer):
    """``default_unit`` and ``tags`` are plain related fields: both point at shared,
    non-owned vocabulary (``Unit``/``Tag``), so there is no per-user visibility to filter and
    ``core/README.md``'s "filter every nested owned relation through ``visible_to()``" rule
    does not apply here.
    """

    class Meta:
        model = Ingredient
        fields = [
            "id",
            "name",
            "default_unit",
            "density_g_per_ml",
            "is_staple",
            "tags",
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

    def validate_name(self, value: str) -> str:
        """Reject a name that would collide with one this user already owns (case-insensitively)
        before it reaches the database's functional unique constraint — a 400 with a clear
        message rather than a bare ``IntegrityError`` 500. Cross-user duplication and
        user-vs-system duplication both stay allowed (design.md, "Ingredient").
        """
        name = value.strip()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return name
        exclude_pk = self.instance.pk if self.instance is not None else None
        if owner_has_ingredient_named(user, name, exclude_pk=exclude_pk):
            raise serializers.ValidationError(f"You already have an ingredient called {name!r}.")
        return name


class ConversionRequestSerializer(serializers.Serializer):
    """Input for ``POST /api/units/convert/``.

    ``quantity`` is a bounded ``DecimalField`` — an unbounded or non-numeric value is a 400
    from DRF's own field validation, never a ``decimal.InvalidOperation`` 500 inside the
    service (04.1-04.5 review, finding #4). ``ingredient`` is scoped to what the requester can
    see, so its density cannot be probed for a row they have no access to.
    """

    quantity = serializers.DecimalField(max_digits=20, decimal_places=10, min_value=Decimal("0"))
    from_unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all())
    to_unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all())
    ingredient = serializers.PrimaryKeyRelatedField(
        queryset=Ingredient.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["ingredient"].queryset = Ingredient.objects.visible_to(user)
