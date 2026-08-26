"""Throwaway serializers exercising ``OwnedSerializer`` against ``core.tests.models`` — see
that module's docstring for why these are test-only, registered only under test settings.
"""

from __future__ import annotations

from rest_framework import serializers

from core.serializers import OwnedSerializer
from core.tests.models import DummyNode, DummyOwned


class DummySerializer(OwnedSerializer):
    class Meta:
        model = DummyOwned
        fields = [
            "id",
            "name",
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


class DummyNodeSerializer(OwnedSerializer):
    """Demonstrates design.md's "every nested serializer must filter through .visible_to()"
    rule (Security notes, #4 — leakage through relations): ``depends_on`` is rendered through
    the requesting user's visibility via a ``SerializerMethodField``, not a bare
    ``PrimaryKeyRelatedField`` over the unfiltered relation, which would leak an invisible
    child's existence into a shared or public parent's serialized output.
    """

    depends_on = serializers.SerializerMethodField()

    class Meta:
        model = DummyNode
        fields = [
            "id",
            "name",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "depends_on",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["depends_on", "created_at", "updated_at"]

    def get_depends_on(self, obj: DummyNode) -> list[int]:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return list(obj.depends_on.visible_to(user).values_list("pk", flat=True))
