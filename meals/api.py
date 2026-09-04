"""DRF viewsets for the meals API (``Plan/06-Dishes-And-RecipeBooks/design.md``, "API";
``core/README.md`` for the owned-model wiring).

``DishViewSet`` and ``RecipeBookViewSet`` are both full owned resources via
``OwnedViewSetMixin``: ``get_queryset()`` through ``.visible_to()``, ``IsOwnerOrReadOnly`` on
the plain verbs, and the ``share`` / ``unshare`` / ``copy`` / ``shares`` actions, all
inherited. On top of CRUD:

- ``GET  /api/dishes/<id>/flattened/`` — the dish's combined, aggregated ingredient list.
- ``POST /api/dishes/<id>/made/`` · ``GET|PUT /api/dishes/<id>/stats/`` — the requester's
  per-user ``DishStats`` (baseline ``CanCopy``, keyed by action name in
  ``core.viewsets._ACTION_PERMISSION_CLASSES``).
- ``POST   /api/recipe-books/<id>/recipes/`` — add ``{recipe, section}``.
- ``DELETE /api/recipe-books/<id>/recipes/<recipe_id>/`` — remove.
- ``PATCH  /api/recipe-books/<id>/reorder/`` — bulk position / section update.

The book mutation actions are POST/DELETE/PATCH, so ``OwnedViewSetMixin``'s default
``IsOwnerOrReadOnly`` baseline already makes them owner-only.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import ProtectedError, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.exceptions import conflict_from_protected_error
from core.viewsets import OwnedViewSetMixin
from meals.filters import DishFilter, RecipeBookFilter
from meals.models import Dish, RecipeBook, RecipeBookEntry
from meals.serializers import (
    AddRecipeToBookSerializer,
    DishSerializer,
    DishStatsSerializer,
    RecipeBookEntrySerializer,
    RecipeBookSerializer,
    ReorderBookSerializer,
)
from meals.services.stats import get_stats, mark_made, set_favorite, set_rating
from recipes.serializers import FlatLineSerializer
from recipes.services.flatten import FlattenError
from recipes.services.graph import GraphError

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _is_true(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUE_VALUES


class DishViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        Dish.objects.all()
        .select_related("owner", "copied_from")
        .prefetch_related(
            "tags",
            "shared_with",
            "components__recipe",
        )
    )
    serializer_class = DishSerializer
    filterset_class = DishFilter

    def get_queryset(self) -> QuerySet[Dish]:
        """``flattened`` walks every component recipe's sub-recipe tree, so it needs the deep
        ``with_component_graph()`` prefetch rather than the single-level one the list and plain
        detail use.
        """
        queryset = super().get_queryset()
        if self.action == "flattened":
            return Dish.objects.with_component_graph().visible_to(self.request.user)
        return queryset

    def perform_destroy(self, instance: Dish) -> None:
        try:
            instance.delete()
        except ProtectedError as exc:  # pragma: no cover - no PROTECT points at Dish yet
            raise conflict_from_protected_error(exc) from exc

    @extend_schema(responses={200: FlatLineSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def flattened(self, request: Request, pk: str | None = None) -> Response:
        dish = self.get_object()
        exclude_staples = _is_true(request.query_params.get("exclude_staples"))
        try:
            lines = dish.flatten(exclude_staples=exclude_staples, viewer=request.user)
        except (GraphError, FlattenError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(FlatLineSerializer(lines, many=True).data)

    @extend_schema(request=None, responses={200: DishStatsSerializer})
    @action(detail=True, methods=["post"])
    def made(self, request: Request, pk: str | None = None) -> Response:
        dish = self.get_object()
        stats = mark_made(request.user, dish)
        return Response(DishStatsSerializer(stats).data)

    @extend_schema(request=DishStatsSerializer, responses={200: DishStatsSerializer})
    @action(detail=True, methods=["get", "put"])
    def stats(self, request: Request, pk: str | None = None) -> Response:
        dish = self.get_object()
        if request.method == "GET":
            return Response(DishStatsSerializer(get_stats(request.user, dish)).data)

        serializer = DishStatsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "rating" in data:
            try:
                set_rating(request.user, dish, data["rating"])
            except DjangoValidationError as exc:
                raise ValidationError({"rating": exc.messages}) from exc
        if "is_favorite" in data:
            set_favorite(request.user, dish, data["is_favorite"])
        return Response(DishStatsSerializer(get_stats(request.user, dish)).data)


class RecipeBookViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        RecipeBook.objects.all()
        .select_related("owner", "copied_from")
        .prefetch_related("shared_with", "entries__recipe")
    )
    serializer_class = RecipeBookSerializer
    filterset_class = RecipeBookFilter

    @staticmethod
    def _next_position(book: RecipeBook, section: str) -> int:
        existing = [e.position for e in book.entries.all() if e.section == section]
        return (max(existing) + 1) if existing else 0

    @extend_schema(request=AddRecipeToBookSerializer, responses={201: RecipeBookEntrySerializer})
    @action(detail=True, methods=["post"], url_path="recipes")
    def add_recipe(self, request: Request, pk: str | None = None) -> Response:
        """Add a recipe to the book. The recipe must be ``visible_to`` the requester — an
        invisible ID reads as "does not exist" (``design.md``: "the sneakiest read primitive
        in the app").
        """
        book = self.get_object()
        serializer = AddRecipeToBookSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        recipe = serializer.validated_data["recipe"]
        section = serializer.validated_data.get("section", "")

        if RecipeBookEntry.objects.filter(book=book, recipe=recipe).exists():
            raise ValidationError({"recipe": "That recipe is already in this book."})

        entry = RecipeBookEntry.objects.create(
            book=book,
            recipe=recipe,
            section=section,
            position=self._next_position(book, section),
        )
        return Response(RecipeBookEntrySerializer(entry).data, status=201)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"recipes/(?P<recipe_id>[^/.]+)")
    def remove_recipe(
        self, request: Request, pk: str | None = None, recipe_id: str | None = None
    ) -> Response:
        book = self.get_object()
        try:
            recipe_pk = int(recipe_id)
        except (TypeError, ValueError) as exc:
            raise NotFound("That recipe is not in this book.") from exc
        deleted, _ = RecipeBookEntry.objects.filter(book=book, recipe_id=recipe_pk).delete()
        if not deleted:
            raise NotFound("That recipe is not in this book.")
        return Response(status=204)

    @extend_schema(request=ReorderBookSerializer, responses={200: RecipeBookSerializer})
    @action(detail=True, methods=["patch"], url_path="reorder")
    def reorder(self, request: Request, pk: str | None = None) -> Response:
        book = self.get_object()
        serializer = ReorderBookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["entries"]

        known_ids = set(
            RecipeBookEntry.objects.filter(book=book).values_list("recipe_id", flat=True)
        )
        unknown = sorted({item["recipe"] for item in items} - known_ids)
        if unknown:
            raise ValidationError({"entries": f"These recipes are not in this book: {unknown}."})

        with transaction.atomic():
            for item in items:
                fields = {"position": item["position"]}
                if "section" in item:
                    fields["section"] = item["section"]
                RecipeBookEntry.objects.filter(book=book, recipe_id=item["recipe"]).update(**fields)

        book.refresh_from_db()
        return Response(RecipeBookSerializer(book, context=self.get_serializer_context()).data)
