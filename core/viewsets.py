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
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

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
# pitfall). Composing with a list baked in once at import time would silently drop
# ``IsAuthenticated`` and ``ForcePasswordChangeAPIPermission`` from every owned endpoint the
# moment a test (or, in principle, a settings reload) changed ``DEFAULT_PERMISSION_CLASSES``
# after this module first loaded (03.8a / NB5) — ``get_permissions()`` below reads
# ``api_settings.DEFAULT_PERMISSION_CLASSES`` fresh on every call instead.
_ACTION_PERMISSION_CLASSES: dict[str, type[BasePermission]] = {
    "share": IsOwner,
    "unshare": IsOwner,
    # shares audience list is as sensitive as share/unshare — see the `shares` action itself.
    "shares": IsOwner,
    "copy": CanCopy,
    # Per-user stats actions (task 05's `made` / `stats`): the write lands on a
    # ``RecipeStats``/``DishStats`` row keyed to ``request.user``, never on the owned object
    # itself, so ``IsOwnerOrReadOnly`` is the wrong gate — a recipe shared or made public to
    # someone exists precisely so they can rate it and mark it made. ``CanCopy`` ("if you can
    # see it, you can act on your own copy of its per-user state") is the right rule; the
    # object is still fetched through ``.visible_to()`` first, so an invisible one 404s.
    "made": CanCopy,
    "stats": CanCopy,
}


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

    filter_backends = [*api_settings.DEFAULT_FILTER_BACKENDS, OwnedObjectFilterBackend]

    def get_permissions(self) -> list[BasePermission]:
        """Composes three layers, always additively, never as a replacement of one another:

        1. The project's ``DEFAULT_PERMISSION_CLASSES`` — read live from ``api_settings`` on
           every call, not a snapshot taken once at import time.
        2. This mixin's own action-keyed baseline: ``IsOwner`` for the three owner-only
           actions, ``CanCopy`` for ``copy``, ``IsOwnerOrReadOnly`` for every plain CRUD verb.
           This is the object-level guard that actually gates writes and the sensitive
           ``/shares/`` read — it must never be displaced by an explicit override, only added
           to, or a viewset that declares its own ``permission_classes`` for an unrelated
           reason (e.g. to require staff on top of ownership) would silently lose ownership
           enforcement entirely.
        3. An explicit ``permission_classes`` declaration, if any — a subclass's class
           attribute, or an ``@action(..., permission_classes=[...])`` kwarg (Django's
           ``View.__init__`` setattrs an action's initkwargs onto the instance, which is how
           DRF's router wires per-action overrides). Detected by identity against
           ``APIView.permission_classes`` (the un-overridden default every ``APIView``
           inherits).

        Layer 3 is appended on top of layer 2, not substituted for it: a declared override can
        only ever tighten what the mixin already requires, exactly as ``core/README.md``
        documents. The earlier shape of this method treated an explicit declaration as
        *replacing* layer 2 outright, which silently dropped ``IsOwnerOrReadOnly``/``IsOwner``
        the moment any subclass or ``@action`` declared its own ``permission_classes`` for any
        reason — reopening the flagship IDOR this mixin exists to close.

        DRF calls this fresh on every request (``APIView.initial()``, after ``self.action`` is
        already set), so there is no caching to go stale either.
        """
        action_name = getattr(self, "action", None)
        extra_permission_classes = [_ACTION_PERMISSION_CLASSES.get(action_name, IsOwnerOrReadOnly)]
        if self.permission_classes is not APIView.permission_classes:
            extra_permission_classes.extend(self.permission_classes)
        permission_classes = [*api_settings.DEFAULT_PERMISSION_CLASSES, *extra_permission_classes]
        return [permission_class() for permission_class in permission_classes]

    def get_queryset(self) -> QuerySet[OwnedModel]:
        return super().get_queryset().visible_to(self.request.user)

    @action(detail=True, methods=["post"])
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

    @action(detail=True, methods=["post"])
    def unshare(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        serializer = _UnshareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unshare_object(obj, actor=request.user, users=list(serializer.validated_data["users"]))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        try:
            new_obj = copy_object(obj, actor=request.user)
        except (GraphError, CopyError) as exc:
            raise drf_serializers.ValidationError({"detail": str(exc)}) from exc
        serializer = self.get_serializer(new_obj)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def shares(self, request: Request, pk: str | None = None) -> Response:
        obj = self.get_object()
        sharees = _ShareeSerializer(obj.shared_with.all(), many=True).data
        return Response(sharees)
