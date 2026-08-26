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

``visibility`` is readable but not writable through the plain CRUD serializer: changes go
through ``core.services.sharing.share()``/``set_visibility()`` (via ``/share/`` or a future
HTMX form), which run the cascade check a bare ``PATCH`` has no way to know about. Letting
``ModelSerializer`` generate its usual writable ``ChoiceField`` for ``visibility`` would open a
second write path to the same field that skips that check entirely (MILESTONES.md section 6:
"never implement the same rule twice").
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from core.models import Visibility


class OwnedSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    is_system = serializers.BooleanField(read_only=True)
    shared_with = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    copied_from = serializers.PrimaryKeyRelatedField(read_only=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, read_only=True)

    def create(self, validated_data: dict[str, Any]) -> Any:
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)
