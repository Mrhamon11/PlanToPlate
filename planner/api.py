"""DRF viewsets for the meal-planner API (``Plan/08-Meal-Planner/design.md``, "API").

Two resources:

- ``MealPlanProfileViewSet`` — CRUD on the eight gears. **A profile is private to its owner**:
  ``get_queryset()`` is scoped to ``owner=request.user`` (there is no visibility model on a
  profile — it is not an ``OwnedModel``), so another user's profile 404s.
- ``MealPlanViewSet`` — a full owned resource via ``OwnedViewSetMixin`` (``get_queryset()``
  through ``.visible_to()``, ``IsOwnerOrReadOnly`` on writes, plus ``share`` / ``unshare`` /
  ``shares``). The inherited ``copy`` action is **overridden to 405** — plan-copy is out of
  scope (D44) and the ownership transfer would leak the owner's ``profile_snapshot``. On
  top of CRUD:
    - ``POST /api/planner/plans/generate/`` — a preview, unsaved.
    - ``POST /api/planner/plans/`` — persist a preview (regenerated from its seed).
    - ``POST /api/planner/plans/<id>/regenerate/`` — re-roll unlocked slots in place.
    - ``PATCH /api/planner/plans/<id>/entries/<entry_id>/`` — manual swap / lock / clear.
    - ``POST  /api/planner/plans/<id>/entries/<entry_id>/reroll/`` — re-roll one slot.
    - ``POST  /api/planner/plans/<id>/generate-shopping-list/``.
    - ``GET   /api/planner/plans/<id>/preview-shopping-list/``.

Every generate / persist / regenerate path resolves ``profile`` through the requester's own
profiles (the request serializer's scoped queryset), so ``profile.owner == request.user`` is
structurally guaranteed — ``build_candidate_pool`` and the generator would otherwise apply
someone else's knobs (08.10 carried finding).
"""

from __future__ import annotations

import random

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.viewsets import OwnedViewSetMixin
from lists.serializers import ShoppingResultSerializer, visible_item_target_caches
from lists.services import ListVisibilityError
from planner.models import MealPlan, MealPlanProfile
from planner.serializers import (
    SEED_MAX,
    GeneratePreviewSerializer,
    MealPlanEntrySerializer,
    MealPlanProfileSerializer,
    MealPlanSerializer,
    PersistPlanSerializer,
    PlanResultSerializer,
    RegeneratePlanSerializer,
    RerollEntrySerializer,
    ShoppingListActionSerializer,
    ShoppingPreviewSerializer,
)
from planner.services.exceptions import PlannerError
from planner.services.generate import generate_plan, regenerate_plan
from planner.services.persist import (
    reroll_entry,
    save_plan,
    update_plan_in_place,
)
from planner.services.shopping import generate_shopping_list as generate_shopping_list_service
from planner.services.shopping import preview_shopping_list as preview_shopping_list_service


def _random_seed() -> int:
    return random.randrange(SEED_MAX)  # noqa: S311 - a plan seed, not a secret (C9)


class MealPlanProfileViewSet(viewsets.ModelViewSet):
    serializer_class = MealPlanProfileSerializer

    def get_queryset(self) -> QuerySet[MealPlanProfile]:
        return (
            MealPlanProfile.objects.filter(owner=self.request.user)
            .prefetch_related("excluded_tags", "excluded_ingredients")
            .order_by("name")
        )


class MealPlanViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = (
        MealPlan.objects.all()
        .select_related("owner", "copied_from", "profile", "shopping_list")
        .prefetch_related("shared_with", "entries__dish")
    )
    serializer_class = MealPlanSerializer

    # --- plan-copy is deliberately blocked (D44) ------------------------------------------

    @action(detail=True, methods=["post"])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        """**Blocked — 405.** ``OwnedViewSetMixin.copy`` transfers ownership to the requester,
        which for a ``MealPlan`` would (a) hand anyone who can see the plan the owner's
        ``profile_snapshot`` (their allergy list / tag limits / profile name — owner-only on
        read, D35) because ``get_profile_snapshot`` keys off the new ``owner_id``, and
        (b) leave ``profile`` / ``shopping_list`` as live FKs into the original owner's
        private rows. D44 puts plan-copy out of scope; a real implementation needs a
        ``copy_children`` hook that deep-copies entries and resets
        ``profile`` / ``shopping_list`` / ``profile_snapshot`` — a separate task.
        """
        raise MethodNotAllowed(request.method or "POST")

    # --- persist a preview ------------------------------------------------------------------

    @extend_schema(request=PersistPlanSerializer, responses={201: MealPlanSerializer})
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = PersistPlanSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = data["profile"]
        seed = data.get("seed")
        if seed is None:
            seed = _random_seed()
        days = data.get("days") or profile.days

        result = generate_plan(request.user, profile, seed=seed, days=days)
        plan = save_plan(
            request.user,
            result,
            profile=profile,
            start_date=data["start_date"],
            name=data.get("name") or "",
            days=days,
        )
        return Response(
            MealPlanSerializer(plan, context=self.get_serializer_context()).data, status=201
        )

    # --- preview (unsaved) ----------------------------------------------------------------

    @extend_schema(request=GeneratePreviewSerializer, responses={200: PlanResultSerializer})
    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request: Request) -> Response:
        serializer = GeneratePreviewSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        seed = data.get("seed")
        if seed is None:
            seed = _random_seed()

        result = generate_plan(request.user, data["profile"], seed=seed)
        return Response(PlanResultSerializer(result, context=self.get_serializer_context()).data)

    # --- regenerate in place ------------------------------------------------------------

    @extend_schema(request=RegeneratePlanSerializer, responses={200: MealPlanSerializer})
    @action(detail=True, methods=["post"], url_path="regenerate")
    def regenerate(self, request: Request, pk: str | None = None) -> Response:
        plan = self.get_object()
        serializer = RegeneratePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = regenerate_plan(plan, seed=serializer.validated_data.get("seed"))
        except PlannerError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        update_plan_in_place(plan, result, seed=result.seed)
        plan = self.get_queryset().get(pk=plan.pk)
        return Response(MealPlanSerializer(plan, context=self.get_serializer_context()).data)

    # --- one entry: swap / lock / clear -------------------------------------------------

    @extend_schema(request=MealPlanEntrySerializer, responses={200: MealPlanEntrySerializer})
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"entries/(?P<entry_id>[^/.]+)",
    )
    def entry_detail(
        self, request: Request, pk: str | None = None, entry_id: str | None = None
    ) -> Response:
        plan = self.get_object()
        entry = get_object_or_404(plan.entries.all(), pk=entry_id)
        serializer = MealPlanEntrySerializer(
            entry, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MealPlanEntrySerializer(entry, context=self.get_serializer_context()).data)

    @extend_schema(request=RerollEntrySerializer, responses={200: MealPlanEntrySerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path=r"entries/(?P<entry_id>[^/.]+)/reroll",
    )
    def reroll(
        self, request: Request, pk: str | None = None, entry_id: str | None = None
    ) -> Response:
        plan = self.get_object()
        entry = get_object_or_404(plan.entries.all(), pk=entry_id)
        serializer = RerollEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reroll_entry(plan, entry, seed=serializer.validated_data.get("seed"))
        except PlannerError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(MealPlanEntrySerializer(entry, context=self.get_serializer_context()).data)

    # --- shopping list ----------------------------------------------------------------

    @extend_schema(request=ShoppingListActionSerializer, responses={200: ShoppingResultSerializer})
    @action(detail=True, methods=["post"], url_path="generate-shopping-list")
    def generate_shopping_list(self, request: Request, pk: str | None = None) -> Response:
        plan = self.get_object()
        serializer = ShoppingListActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = generate_shopping_list_service(
                plan, exclude_staples=serializer.validated_data.get("exclude_staples")
            )
        except ListVisibilityError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        context = self.get_serializer_context()
        context.update(visible_item_target_caches(result.items, request.user))
        return Response(ShoppingResultSerializer(result, context=context).data)

    @extend_schema(
        parameters=[ShoppingListActionSerializer], responses={200: ShoppingPreviewSerializer}
    )
    @action(detail=True, methods=["get"], url_path="preview-shopping-list")
    def preview_shopping_list(self, request: Request, pk: str | None = None) -> Response:
        plan = self.get_object()
        if plan.owner_id != request.user.id:
            raise PermissionDenied("Only the plan's owner can preview its shopping list.")
        raw = request.query_params.get("exclude_staples")
        exclude_staples = None if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}
        try:
            preview = preview_shopping_list_service(plan, exclude_staples=exclude_staples)
        except ListVisibilityError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(ShoppingPreviewSerializer(preview).data)
