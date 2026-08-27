"""DRF viewsets for the catalog API (``Plan/04-Units-And-Ingredients/design.md``, "API";
``core/README.md`` for the owned-model wiring).

- ``UnitViewSet`` / ``TagViewSet`` — shared vocabulary, not owned. Everyone reads; only staff
  writes (``StaffWriteReadOnly``). Not paginated: both are small, bounded lists a client wants
  whole to build a picker.
- ``IngredientViewSet`` — a full owned resource via ``OwnedViewSetMixin``: ``get_queryset()``
  through ``.visible_to()``, ``IsOwnerOrReadOnly`` on writes, and the ``share``/``unshare``/
  ``copy``/``shares`` actions, all inherited. ``perform_destroy`` additionally turns a
  ``PROTECT``ed delete into a 409 (04.8).
- ``POST /api/units/convert/`` — a detail=False action on ``UnitViewSet`` so it lands at the
  design's URL and shows in ``/api/docs/``.
"""

from __future__ import annotations

from django.db.models import ProtectedError
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.permissions import ForcePasswordChangeAPIPermission
from catalog.exceptions import IncompatibleUnits
from catalog.filters import IngredientFilter, TagFilter, UnitFilter
from catalog.models import Ingredient, Tag, Unit
from catalog.serializers import (
    ConversionRequestSerializer,
    IngredientSerializer,
    TagSerializer,
    UnitSerializer,
)
from catalog.services.units import convert
from core.exceptions import conflict_from_protected_error
from core.viewsets import OwnedViewSetMixin

# The project default permission stack, named once so the read-only viewsets and the
# per-action override below compose with it instead of silently replacing it.
_BASE_PERMISSIONS = [IsAuthenticated, ForcePasswordChangeAPIPermission]


class StaffWriteReadOnly(BasePermission):
    """Any authenticated user may read; only staff may create, update, or delete. For the
    shared ``Unit``/``Tag`` vocabulary, which is admin-managed (design.md, "Units": "New units
    are added by an admin").
    """

    def has_permission(self, request: Request, view: object) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [*_BASE_PERMISSIONS, StaffWriteReadOnly]
    filterset_class = UnitFilter
    pagination_class = None

    @extend_schema(request=ConversionRequestSerializer, responses={200: None})
    @action(detail=False, methods=["post"], permission_classes=_BASE_PERMISSIONS)
    def convert(self, request: Request) -> Response:
        """Convert a quantity from one unit to another, or a 400 naming why it is impossible."""
        serializer = ConversionRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = convert(
                data["quantity"],
                data["from_unit"],
                data["to_unit"],
                ingredient=data.get("ingredient"),
            )
        except IncompatibleUnits as exc:
            raise ValidationError(
                {
                    "detail": str(exc),
                    "from_unit": exc.from_unit.name,
                    "to_unit": exc.to_unit.name,
                    "reason": exc.reason,
                }
            ) from exc
        return Response(
            {
                "quantity": result,
                "from_unit": data["from_unit"].pk,
                "to_unit": data["to_unit"].pk,
                "unit": data["to_unit"].abbrev,
            }
        )


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [*_BASE_PERMISSIONS, StaffWriteReadOnly]
    filterset_class = TagFilter
    pagination_class = None


class IngredientViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        Ingredient.objects.all()
        .select_related("default_unit", "owner", "copied_from")
        .prefetch_related("tags")
    )
    serializer_class = IngredientSerializer
    filterset_class = IngredientFilter

    def perform_destroy(self, instance: Ingredient) -> None:
        """A recipe component (task 05) points a ``PROTECT`` FK at ``Ingredient``; deleting an
        in-use ingredient must be a 409 naming the blockers, not a 500 or a silent cascade
        (design.md, "API").
        """
        try:
            instance.delete()
        except ProtectedError as exc:
            raise conflict_from_protected_error(exc) from exc
