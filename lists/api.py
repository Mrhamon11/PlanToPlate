"""DRF viewset for the lists API (``Plan/07-Lists-And-Shopping/design.md``, "API";
``core/README.md`` for the owned-model wiring).

``ListViewSet`` is a full owned resource via ``OwnedViewSetMixin``: ``get_queryset()`` through
``.visible_to()``, ``IsOwnerOrReadOnly`` on the plain verbs and every mutating action, and the
inherited ``share`` / ``unshare`` / ``copy`` / ``shares`` actions. On top of CRUD:

- ``GET|POST /api/lists/<id>/items/`` — page the items, or append one.
- ``PATCH|DELETE /api/lists/<id>/items/<item_id>/`` — edit / check / remove one item.
- ``PATCH /api/lists/<id>/reorder/`` — bulk positions.
- ``POST /api/lists/<id>/add-dish/`` — expand a dish onto a shopping list.
- ``POST /api/lists/<id>/clear-checked/`` · ``POST /api/lists/<id>/merge-duplicates/``.
- ``GET /api/lists/default-shopping/`` — get or create the caller's default shopping list.

Every mutating action calls ``self.get_object()`` first, so a list the caller cannot see 404s
and a list they can see but do not own 403s on an unsafe verb — a shared list is read-only for
the recipient (design.md, "Edge cases"), collaborative editing is out of scope.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.viewsets import OwnedViewSetMixin
from lists.filters import ListFilter
from lists.models import ItemSource, List
from lists.serializers import (
    AddDishSerializer,
    ListItemSerializer,
    ListSerializer,
    ReorderSerializer,
    ShoppingResultSerializer,
    visible_item_target_caches,
)
from lists.services import (
    ListError,
    add_dish_to_list,
    get_or_create_default_shopping_list,
    merge_duplicate_items,
    next_position,
    reorder_items,
)
from lists.services import clear_checked as clear_checked_service


class ListViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        List.objects.all()
        .select_related("owner", "copied_from")
        .prefetch_related(
            "shared_with",
            "items__recipe",
            "items__dish",
            "items__ingredient",
            "items__unit",
        )
    )
    serializer_class = ListSerializer
    filterset_class = ListFilter

    def _item_context(self, items: object) -> dict:
        context = self.get_serializer_context()
        context.update(visible_item_target_caches(items, self.request.user))
        return context

    @extend_schema(request=None, responses={200: ListSerializer})
    @action(detail=False, methods=["get"], url_path="default-shopping")
    def default_shopping(self, request: Request) -> Response:
        lst = get_or_create_default_shopping_list(request.user)
        return Response(ListSerializer(lst, context=self.get_serializer_context()).data)

    @extend_schema(request=ListItemSerializer, responses={201: ListItemSerializer})
    @action(detail=True, methods=["get", "post"], url_path="items")
    def items(self, request: Request, pk: str | None = None) -> Response:
        lst = self.get_object()

        if request.method == "GET":
            all_items = list(lst.items.all())
            page = self.paginate_queryset(all_items)
            data = ListItemSerializer(page, many=True, context=self._item_context(all_items)).data
            return self.get_paginated_response(data)

        serializer = ListItemSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        item = serializer.save(list=lst, position=next_position(lst), source=ItemSource.MANUAL)
        return Response(
            ListItemSerializer(item, context=self._item_context([item])).data, status=201
        )

    @extend_schema(request=ListItemSerializer, responses={200: ListItemSerializer})
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"items/(?P<item_id>[^/.]+)",
    )
    def item_detail(
        self, request: Request, pk: str | None = None, item_id: str | None = None
    ) -> Response:
        lst = self.get_object()
        item = get_object_or_404(lst.items.all(), pk=item_id)

        if request.method == "DELETE":
            item.delete()
            return Response(status=204)

        serializer = ListItemSerializer(
            item, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except ListError as exc:
            raise ValidationError({"quantity": str(exc)}) from exc
        return Response(ListItemSerializer(item, context=self._item_context([item])).data)

    @extend_schema(request=ReorderSerializer, responses={200: ListSerializer})
    @action(detail=True, methods=["patch"], url_path="reorder")
    def reorder(self, request: Request, pk: str | None = None) -> Response:
        lst = self.get_object()
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reorder_items(lst, serializer.validated_data["item_ids"])
        except ListError as exc:
            raise ValidationError({"item_ids": str(exc)}) from exc
        refreshed = List.objects.get(pk=lst.pk)
        return Response(ListSerializer(refreshed, context=self.get_serializer_context()).data)

    @extend_schema(request=AddDishSerializer, responses={201: ShoppingResultSerializer})
    @action(detail=True, methods=["post"], url_path="add-dish")
    def add_dish(self, request: Request, pk: str | None = None) -> Response:
        lst = self.get_object()
        serializer = AddDishSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            items = add_dish_to_list(
                lst,
                serializer.validated_data["dish"],
                actor=request.user,
                exclude_staples=serializer.validated_data["exclude_staples"],
            )
        except ListError as exc:
            raise ValidationError({"dish": str(exc)}) from exc
        payload = {"added": len(items), "replaced": 0, "staples_skipped": 0, "items": items}
        return Response(
            ShoppingResultSerializer(payload, context=self._item_context(items)).data,
            status=201,
        )

    @extend_schema(request=None, responses={200: None})
    @action(detail=True, methods=["post"], url_path="clear-checked")
    def clear_checked(self, request: Request, pk: str | None = None) -> Response:
        lst = self.get_object()
        removed = clear_checked_service(lst)
        return Response({"removed": removed})

    @extend_schema(request=None, responses={200: None})
    @action(detail=True, methods=["post"], url_path="merge-duplicates")
    def merge_duplicates(self, request: Request, pk: str | None = None) -> Response:
        lst = self.get_object()
        merged = merge_duplicate_items(lst)
        return Response({"merged": merged})
