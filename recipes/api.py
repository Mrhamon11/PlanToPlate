"""DRF viewset for the recipes API (``Plan/05-Recipes/design.md``, "API"; ``core/README.md``
for the owned-model wiring).

``RecipeViewSet`` is a full owned resource via ``OwnedViewSetMixin``: ``get_queryset()`` through
``.visible_to()``, ``IsOwnerOrReadOnly`` on the plain verbs, and the
``share`` / ``unshare`` / ``copy`` / ``shares`` actions, all inherited. On top of CRUD it adds:

- ``GET  /api/recipes/<id>/scaled/?factor=2`` — components with every quantity multiplied,
  nothing persisted.
- ``GET  /api/recipes/<id>/flattened/?exclude_staples=true&factor=2`` — the recursively
  expanded, aggregated ingredient list.
- ``POST /api/recipes/<id>/made/`` — increments the requester's ``times_made`` and stamps
  ``last_made_at``.
- ``GET|PUT /api/recipes/<id>/stats/`` — read or set the requester's rating and favourite.
  The ``PUT`` has **partial semantics**: a key omitted from the body (``is_favorite`` with no
  ``rating``, or vice versa) leaves the stored value untouched rather than resetting it, so a
  one-widget update never has to re-send the other field.

``made`` / ``stats`` write per-user ``RecipeStats`` keyed to ``request.user``, so their
permission baseline is ``CanCopy`` ("if you can see it") not ``IsOwnerOrReadOnly`` — wired in
``core.viewsets._ACTION_PERMISSION_CLASSES``.

``perform_destroy`` turns a ``PROTECT``ed delete (a recipe still used as someone's sub-recipe)
into a 409 naming the parents, via ``recipes.services.deletion`` — the same helper the HTML
delete view uses (05.9).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.viewsets import OwnedViewSetMixin
from recipes.filters import RecipeFilter
from recipes.models import Recipe
from recipes.serializers import (
    FlatLineSerializer,
    RecipeComponentSerializer,
    RecipeSerializer,
    RecipeStatsSerializer,
)
from recipes.services.deletion import conflict_for_protected_recipe
from recipes.services.flatten import FlattenError, aggregate, flatten, scale
from recipes.services.graph import GraphError
from recipes.services.stats import get_stats, mark_made, set_favorite, set_rating

_TRUE_VALUES = {"1", "true", "yes", "on"}

#: Upper bound on ``?factor=``. Generous for any real "cook this for a crowd" use, but low
#: enough that ``quantity * factor`` can never reach ``decimal.Overflow`` and turn a malformed
#: query into a 500. A larger request is a mistake or an attempt to break the endpoint.
_MAX_FACTOR = Decimal(10000)


def _is_true(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUE_VALUES


def _parse_factor(raw: str | None) -> Decimal:
    """``?factor=`` as a ``Decimal`` in ``(0, _MAX_FACTOR]``. Anything non-numeric, non-finite
    (``NaN`` / ``sNaN`` / ``Infinity``), non-positive, or out of range is a 400 — never a
    ``decimal.InvalidOperation`` / ``decimal.Overflow`` 500, nor a division-by-zero or a
    nonsense ``Infinity`` quantity deeper in ``scale`` / ``flatten``.
    """
    if raw is None:
        return Decimal(1)
    try:
        factor = Decimal(raw)
        if not factor.is_finite():
            raise ValidationError({"factor": "Must be a finite number."})
        if factor <= 0:
            raise ValidationError({"factor": "Must be greater than zero."})
        if factor > _MAX_FACTOR:
            raise ValidationError({"factor": f"Must not exceed {_MAX_FACTOR}."})
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"factor": "Must be a number."}) from exc
    return factor


class RecipeViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        Recipe.objects.all()
        .select_related("yield_unit", "owner", "copied_from")
        .prefetch_related(
            "tags",
            "shared_with",
            "components__ingredient",
            "components__unit",
            "components__sub_recipe",
        )
    )
    serializer_class = RecipeSerializer
    filterset_class = RecipeFilter

    def get_queryset(self) -> QuerySet[Recipe]:
        """``flattened`` walks the whole sub-recipe tree, so it needs the deep
        ``with_component_graph()`` prefetch — not the single-level prefetch the list and the
        plain detail view use. Selecting it here means ``flatten`` gets its bounded-query graph
        from the one ``get_object()`` fetch, instead of that fetch being done and then discarded
        for a second ``with_component_graph().get()`` (task 05 review, non-blocking).
        """
        queryset = super().get_queryset()
        if self.action == "flattened":
            return Recipe.objects.with_component_graph().visible_to(self.request.user)
        return queryset

    def perform_destroy(self, instance: Recipe) -> None:
        """A recipe used as someone's sub-recipe is ``PROTECT``ed by ``RecipeComponent``;
        deleting it is a 409 naming the **parent recipes**, not the join rows (05.9). The
        message is built by ``recipes.services.deletion`` — shared with the HTML delete view.
        """
        try:
            instance.delete()
        except ProtectedError as exc:
            raise conflict_for_protected_recipe(exc, viewer=self.request.user) from exc

    @extend_schema(responses={200: RecipeComponentSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def scaled(self, request: Request, pk: str | None = None) -> Response:
        recipe = self.get_object()
        factor = _parse_factor(request.query_params.get("factor"))
        components = scale(recipe, factor)
        data = RecipeComponentSerializer(
            components, many=True, context=self.get_serializer_context()
        ).data
        return Response(data)

    @extend_schema(responses={200: FlatLineSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def flattened(self, request: Request, pk: str | None = None) -> Response:
        # ``get_queryset()`` selects ``with_component_graph()`` for this action, so this single
        # fetch already carries the whole sub-recipe tree and ``flatten`` walks it in a bounded
        # number of queries (design.md, "Performance").
        recipe = self.get_object()
        factor = _parse_factor(request.query_params.get("factor"))
        exclude_staples = _is_true(request.query_params.get("exclude_staples"))
        try:
            lines = aggregate(flatten(recipe, factor=factor, exclude_staples=exclude_staples))
        except (GraphError, FlattenError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(FlatLineSerializer(lines, many=True).data)

    @extend_schema(request=None, responses={200: RecipeStatsSerializer})
    @action(detail=True, methods=["post"])
    def made(self, request: Request, pk: str | None = None) -> Response:
        recipe = self.get_object()
        stats = mark_made(request.user, recipe)
        return Response(RecipeStatsSerializer(stats).data)

    @extend_schema(request=RecipeStatsSerializer, responses={200: RecipeStatsSerializer})
    @action(detail=True, methods=["get", "put"])
    def stats(self, request: Request, pk: str | None = None) -> Response:
        recipe = self.get_object()
        if request.method == "GET":
            return Response(RecipeStatsSerializer(get_stats(request.user, recipe)).data)

        serializer = RecipeStatsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "rating" in data:
            try:
                set_rating(request.user, recipe, data["rating"])
            except DjangoValidationError as exc:
                raise ValidationError({"rating": exc.messages}) from exc
        if "is_favorite" in data:
            set_favorite(request.user, recipe, data["is_favorite"])
        return Response(RecipeStatsSerializer(get_stats(request.user, recipe)).data)
