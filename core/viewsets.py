"""``OwnedViewSetMixin`` — the REST surface of the ownership/visibility keystone (design.md,
"API surface"). Composed into every owned resource's ``ModelViewSet``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core.filters import OwnedObjectFilterBackend
from core.models import Visibility
from core.permissions import CanCopy, IsOwner, IsOwnerOrReadOnly
from core.services.copying import CopyError, copy_object
from core.services.graph import GraphError
from core.services.sharing import SharingError
from core.services.sharing import share as share_object
from core.services.sharing import unshare as unshare_object

if TYPE_CHECKING:
    from core.models import OwnedModel

User = get_user_model()

# DRF only ever calls a view's *own* ``permission_classes``/``filter_backends`` — it does not
# merge them with ``DEFAULT_PERMISSION_CLASSES``/``DEFAULT_FILTER_BACKENDS`` from settings.
# Every place below that sets either therefore composes with the project defaults explicitly
# (``config/settings/base.py``'s own comment on ``SERVE_PERMISSIONS`` documents the same
# pitfall). Setting a bare list here would silently drop ``IsAuthenticated`` and
# ``ForcePasswordChangeAPIPermission`` from every owned endpoint — anonymous access on
# resources that are supposed to require login, and a temp-password holder who should be
# locked out of everything but the password-change endpoint getting unrestricted API access.
_DEFAULT_PERMISSIONS = list(api_settings.DEFAULT_PERMISSION_CLASSES)


class _ShareRequestSerializer(drf_serializers.Serializer):
    users = drf_serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.filter(is_active=True),
        required=False,
        default=list,
    )
    visibility = drf_serializers.ChoiceField(
        choices=Visibility.choices, required=False, allow_null=True, default=None
    )


class _UnshareRequestSerializer(drf_serializers.Serializer):
    users = drf_serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.filter(is_active=True)
    )


class _ShareeSerializer(drf_serializers.Serializer):
    id = drf_serializers.IntegerField()
    username = drf_serializers.CharField()


class OwnedViewSetMixin:
    """``get_queryset()`` routes every list/detail lookup through ``.visible_to(request.user)``
    — the primary defence (design.md, "Permissions"): an invisible object 404s before any
    permission class ever runs. ``IsOwnerOrReadOnly`` is the default object permission for the
    plain CRUD verbs (secondary defence); the four extra actions below use a stricter or looser
    rule where the design calls for one: ``share``/``unshare``/``shares`` are owner-only
    regardless of verb (``IsOwner`` — no safe-method carve-out, since the audience list is
    itself sensitive), and ``copy`` is allowed for anyone who can see the object (``CanCopy``).
    """

    permission_classes = [*_DEFAULT_PERMISSIONS, IsOwnerOrReadOnly]
    filter_backends = [*api_settings.DEFAULT_FILTER_BACKENDS, OwnedObjectFilterBackend]

    def get_queryset(self) -> QuerySet[OwnedModel]:
        return super().get_queryset().visible_to(self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[*_DEFAULT_PERMISSIONS, IsOwner])
    def share(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        serializer = _ShareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = share_object(
                obj,
                actor=request.user,
                users=list(serializer.validated_data.get("users") or []),
                visibility=serializer.validated_data.get("visibility") or None,
            )
        except (SharingError, GraphError) as exc:
            raise drf_serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(
            {
                "shared_with": [user.pk for user in result.users],
                "visibility": obj.visibility,
                "cascaded_to": [dep.pk for dep in result.cascaded_to],
            }
        )

    @action(detail=True, methods=["post"], permission_classes=[*_DEFAULT_PERMISSIONS, IsOwner])
    def unshare(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        serializer = _UnshareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unshare_object(obj, actor=request.user, users=list(serializer.validated_data["users"]))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[*_DEFAULT_PERMISSIONS, CanCopy])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        try:
            new_obj = copy_object(obj, actor=request.user)
        except (GraphError, CopyError) as exc:
            raise drf_serializers.ValidationError({"detail": str(exc)}) from exc
        serializer = self.get_serializer(new_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], permission_classes=[*_DEFAULT_PERMISSIONS, IsOwner])
    def shares(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        sharees = _ShareeSerializer(obj.shared_with.all(), many=True).data
        return Response(sharees)
