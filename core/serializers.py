"""``OwnedSerializer`` — the base every owned resource's serializer extends (design.md,
"API surface"; MILESTONES.md section 6, "Mass-assignment of owner").

``owner``, ``is_system``, ``shared_with``, ``copied_from``, and ``visibility`` are declared
read-only *here*, not merely via a subclass's ``Meta.read_only_fields`` — so a subclass that
lists them in its own ``Meta.fields`` gets the read-only behaviour automatically rather than
needing to repeat it correctly on every model. DRF strips a read-only field from
``validated_data`` before ``create()``/``update()`` ever run, so client-supplied
``owner``/``is_system``/``shared_with``/``visibility`` never reaches the write path at all —
``owner`` is then set from ``request.user`` explicitly on create, the only place it is ever
assigned.

``shared_with`` is additionally **owner-only on read**: it is a ``SerializerMethodField`` that
returns the audience list only when the requester owns the object, and ``[]`` for everyone
else — a read-only holder, or any viewer of a ``PUBLIC`` object. The share audience is itself
sensitive (``Plan/03-Ownership-And-Sharing/design.md``: "the audience list is itself
sensitive"; ``ARCHITECTURE.md`` D35), and the dedicated ``/shares/`` action already gates it to
the owner — a subclass listing ``shared_with`` in ``Meta.fields`` must not become a second,
ungated path to the same data. Every downstream owned resource inherits this by extending
``OwnedSerializer``.

``visibility`` is readable but not writable through the plain CRUD serializer: changes go
through ``core.services.sharing.share()``/``set_visibility()`` (via ``/share/`` or a future
HTMX form), which run the cascade check a bare ``PATCH`` has no way to know about. Letting
``ModelSerializer`` generate its usual writable ``ChoiceField`` for ``visibility`` would open a
second write path to the same field that skips that check entirely (MILESTONES.md section 6:
"never implement the same rule twice").
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import Visibility
from core.services.dashboard import EmptyPanel


class OwnedSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    is_system = serializers.BooleanField(read_only=True)
    shared_with = serializers.SerializerMethodField()
    copied_from = serializers.PrimaryKeyRelatedField(read_only=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, read_only=True)

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_shared_with(self, obj: Any) -> list[int]:
        """The share audience, but only to the object's owner — ``[]`` for anyone else. See
        this module's docstring and ``ARCHITECTURE.md`` D35 for why this is not a plain
        related field.
        """
        request = self.context.get("request")
        user_id = getattr(getattr(request, "user", None), "id", None)
        if user_id is not None and user_id == obj.owner_id:
            return [user.pk for user in obj.shared_with.all()]
        return []

    def create(self, validated_data: dict[str, Any]) -> Any:
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


# --- Home dashboard (task 12) -------------------------------------------------------------
#
# Read-only projections of ``core.services.dashboard.DashboardContext`` and its panel
# dataclasses. ``GET /api/dashboard/`` serialises exactly what the HTMX home page renders —
# one panel implementation, two renderings (``ARCHITECTURE.md`` section 6). Nothing here is
# writable: the API is a mirror of the service, never a second way to change anything.


class ObjectCardSerializer(serializers.Serializer):
    kind = serializers.CharField()
    name = serializers.CharField()
    url = serializers.CharField()
    owner_username = serializers.CharField(allow_null=True)


class SectionCountSerializer(serializers.Serializer):
    label = serializers.CharField()
    url = serializers.CharField()
    count = serializers.IntegerField()


class PlannedSlotSerializer(serializers.Serializer):
    slot = serializers.CharField()
    slot_label = serializers.CharField()
    dish_name = serializers.CharField(allow_null=True)
    dish_url = serializers.CharField(allow_null=True)


class PlannedDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    day_index = serializers.IntegerField()
    is_today = serializers.BooleanField()
    slots = PlannedSlotSerializer(many=True)


class ThisWeekPanelSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    plan_name = serializers.CharField()
    plan_url = serializers.CharField()
    days = PlannedDaySerializer(many=True)


class ShoppingItemSerializer(serializers.Serializer):
    """One preview line of the shopping panel — decorated by ``lists.services.annotate_display``."""

    label = serializers.CharField(source="display_label")
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, allow_null=True)
    hidden = serializers.BooleanField(source="content_hidden")
    unit = serializers.SerializerMethodField()

    def get_unit(self, item: Any) -> str | None:
        return item.unit.abbrev if item.unit_id else None


class AisleGroupSerializer(serializers.Serializer):
    name = serializers.CharField()
    items = ShoppingItemSerializer(many=True)


class ShoppingPanelSerializer(serializers.Serializer):
    list_id = serializers.IntegerField()
    name = serializers.CharField()
    url = serializers.CharField()
    checked = serializers.IntegerField()
    total = serializers.IntegerField()
    hidden_unchecked = serializers.IntegerField()
    groups = AisleGroupSerializer(many=True)


class EmptyPanelSerializer(serializers.Serializer):
    """A flagship panel with nothing to show yet — carries only the forward URL for its CTA
    (``core.services.dashboard.EmptyPanel``). "This week" / "Shopping" always carry a payload,
    never ``null`` (``design.md`` panel table).
    """

    forward_url = serializers.CharField()


class DashboardSerializer(serializers.Serializer):
    this_week = serializers.SerializerMethodField()
    shopping = serializers.SerializerMethodField()
    recently_viewed = ObjectCardSerializer(many=True)
    favourites = ObjectCardSerializer(many=True)
    shared_with_you = ObjectCardSerializer(many=True)
    public_from_others = ObjectCardSerializer(many=True)
    suggestion = ObjectCardSerializer(allow_null=True)
    sections = SectionCountSerializer(many=True)
    show_get_started = serializers.BooleanField()

    @extend_schema_field(ThisWeekPanelSerializer)
    def get_this_week(self, ctx: Any) -> dict[str, Any]:
        panel = ctx.this_week
        if isinstance(panel, EmptyPanel):
            return EmptyPanelSerializer(panel).data
        return ThisWeekPanelSerializer(panel).data

    @extend_schema_field(ShoppingPanelSerializer)
    def get_shopping(self, ctx: Any) -> dict[str, Any]:
        panel = ctx.shopping
        if isinstance(panel, EmptyPanel):
            return EmptyPanelSerializer(panel).data
        return ShoppingPanelSerializer(panel).data
