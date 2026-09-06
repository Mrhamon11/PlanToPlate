"""HTML (HTMX) views for the meal planner (``Plan/08-Meal-Planner/design.md``, "UI").

- 08.11 — the **profile editor** (the eight gears, grouped *When* / *What* / *Limits* /
  *Quality*). A profile is private to its owner (no visibility model — not an ``OwnedModel``),
  so every profile queryset is scoped to ``owner=request.user``.
- 08.12 — the planner **landing page**, the **generate screen** (form → unsaved preview grid
  → stateless save), the saved-plan **week grid** with per-slot lock / reroll / manual-swap
  HTMX, regenerate, and the D39 ``days``-change confirmation.
- 08.13 — the **shopping-list preview** (staples toggle + the task-07 checked-items warning).
- 08.14 — the **empty-state** guidance shown instead of a blank grid.

Every plan write path goes through ``_owned_plan`` (``visible_to`` + owner-only for writes),
the HTML-side twin of ``MealPlanViewSet``'s ``OwnedViewSetMixin``.
"""

from __future__ import annotations

import datetime
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from catalog.models import Ingredient, Tag
from core.mixins import OwnedObjectMixin
from lists.models import ItemSource
from lists.services import ListError
from meals.models import Dish
from planner.models import (
    DEFAULT_NO_REPEAT_DAYS,
    MAX_DAYS,
    DishTemplate,
    MealPlan,
    MealPlanEntry,
    MealPlanProfile,
    MealSlot,
    SourceScope,
    validate_tag_limits,
)
from planner.services.exceptions import PlannerError
from planner.services.generate import generate_plan, regenerate_plan
from planner.services.persist import (
    reconcile_entries,
    reroll_entry,
    save_plan,
    snapshot_slots,
    update_plan_in_place,
)
from planner.services.shopping import generate_shopping_list, preview_shopping_list

_SLOT_ORDER = {slot: index for index, slot in enumerate(MealSlot.values)}


def _slot_sort_key(slot: str) -> int:
    """Chronological meal order (breakfast → lunch → dinner). ``MealPlanEntry.Meta.ordering``
    sorts ``slot`` alphabetically (BREAKFAST, DINNER, LUNCH) — the grid must not inherit that
    (08.12 carried review finding).
    """
    return _SLOT_ORDER.get(slot, len(_SLOT_ORDER))


class MealPlanProfileForm(forms.ModelForm):
    """The eight gears as one form.

    ``slots`` is a ``JSONField`` on the model (a list of ``MealSlot`` values); the form exposes
    it as a checkbox group and round-trips it to/from that list. ``tag_limits`` stays a raw
    JSON object field — it is the one advanced gear with no natural widget — with its model
    validator re-run here.
    """

    slots = forms.MultipleChoiceField(
        choices=MealSlot.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Which meals to plan each day.",
    )

    #: (section title, ordered field names) — the four groups ``design.md`` calls for, plus the
    #: shopping-list toggle that is not one of the eight gears but belongs on this screen.
    SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("When", ("days", "slots")),
        ("What", ("dish_template", "source_scope")),
        ("Limits", ("tag_limits", "excluded_tags", "excluded_ingredients", "no_repeat_days")),
        ("Quality", ("min_rating", "favorites_only", "favorites_bias", "max_total_minutes")),
        ("Shopping list", ("exclude_staples",)),
    )

    class Meta:
        model = MealPlanProfile
        fields = [
            "name",
            "is_default",
            "days",
            "slots",
            "dish_template",
            "source_scope",
            "tag_limits",
            "excluded_tags",
            "excluded_ingredients",
            "no_repeat_days",
            "min_rating",
            "favorites_only",
            "favorites_bias",
            "max_total_minutes",
            "exclude_staples",
        ]
        widgets = {
            "dish_template": forms.RadioSelect,
            "source_scope": forms.RadioSelect,
            "excluded_tags": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user = user
        self.fields["excluded_tags"].queryset = Tag.objects.order_by("name")
        self.fields["excluded_ingredients"].queryset = Ingredient.objects.visible_to(user).order_by(
            "name"
        )
        for optional in ("min_rating", "max_total_minutes", "tag_limits", "no_repeat_days"):
            self.fields[optional].required = False

        help_texts = {
            "days": "How many days to plan (1–7).",
            "dish_template": "Balanced, one-pot, or a mix.",
            "source_scope": "Which dishes the planner may choose from.",
            "tag_limits": 'Weekly caps by tag, as JSON — e.g. {"chicken": 1, "beef": 2}.',
            "no_repeat_days": "Never repeat a dish cooked within this many days.",
            "min_rating": "Only dishes you have rated at least this (1–5).",
            "favorites_bias": "How much more often to pick a favourite (1 = no bias).",
            "max_total_minutes": "Prep + cook budget per meal, in minutes.",
        }
        for name, text in help_texts.items():
            self.fields[name].help_text = text

        if not self.is_bound:
            self.initial.setdefault("slots", list(self.instance.slots or [MealSlot.DINNER.value]))
            self.initial.setdefault("dish_template", DishTemplate.BALANCED)
            self.initial.setdefault("source_scope", SourceScope.SHARED)

    def clean_slots(self) -> list[str]:
        slots = self.cleaned_data.get("slots") or []
        if not slots:
            raise forms.ValidationError("Choose at least one meal slot.")
        return list(slots)

    def clean_tag_limits(self) -> dict:
        value = self.cleaned_data.get("tag_limits")
        if value in (None, ""):
            return {}
        validate_tag_limits(value)  # raises forms.ValidationError on a bad shape
        return value

    def clean_no_repeat_days(self) -> int:
        value = self.cleaned_data.get("no_repeat_days")
        if value in (None, ""):
            # A blank/cleared field falls back to the design default, not 0 — 0 would
            # silently disable no-repeat protection (08 reviewer finding, owner decision).
            return DEFAULT_NO_REPEAT_DAYS
        return value

    def grouped(self) -> list[dict[str, Any]]:
        """The bound fields arranged into ``SECTIONS`` for the template."""
        return [
            {"title": title, "fields": [self[name] for name in names]}
            for title, names in self.SECTIONS
        ]


class _ProfileScopedMixin(LoginRequiredMixin):
    model = MealPlanProfile
    extra_context = {"nav_active": "planner"}

    def get_queryset(self) -> QuerySet[MealPlanProfile]:
        return MealPlanProfile.objects.filter(owner=self.request.user).order_by("name")


class ProfileListView(_ProfileScopedMixin, ListView):
    template_name = "planner/profile_list.html"
    context_object_name = "profiles"


class _ProfileEditMixin(_ProfileScopedMixin):
    form_class = MealPlanProfileForm
    template_name = "planner/profile_form.html"

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        if form.cleaned_data.get("is_default"):
            # One default per owner is a partial unique constraint — clear the old default
            # before saving the new one or the write 500s on IntegrityError.
            others = MealPlanProfile.objects.filter(owner=self.request.user, is_default=True)
            if form.instance.pk:
                others = others.exclude(pk=form.instance.pk)
            others.update(is_default=False)
        response = super().form_valid(form)
        messages.success(self.request, f'Saved "{self.object.name}".')
        return response


class ProfileCreateView(_ProfileEditMixin, CreateView):
    pass


class ProfileUpdateView(_ProfileEditMixin, UpdateView):
    pass


class ProfileDeleteView(_ProfileScopedMixin, DeleteView):
    template_name = "planner/profile_confirm_delete.html"
    context_object_name = "profile"
    success_url = reverse_lazy("planner:profile-list")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f'Deleted "{name}".')
        return response


# =====================================================================================
# Generate screen + plan grid (08.12), shopping preview (08.13), empty state (08.14)
# =====================================================================================


def _has_any_dish(user: Any) -> bool:
    return Dish.objects.visible_to(user).filter(components__isnull=False).exists()


def _owned_plan(request: HttpRequest, pk: int) -> MealPlan:
    """A plan the requester **owns**. Invisible → 404; merely shared → 403 on any write
    (a shared plan is read-only, D44 / D40)."""
    plan = get_object_or_404(
        MealPlan.objects.visible_to(request.user).select_related("profile", "shopping_list"),
        pk=pk,
    )
    if plan.owner_id != request.user.id:
        raise PermissionDenied("A plan shared with you is read-only.")
    return plan


def _grid_rows(
    entries: list[MealPlanEntry],
    *,
    reasons: dict[tuple[int, str], str],
    days: int,
    slots: list[str],
    start_date: datetime.date | None,
) -> list[dict[str, Any]]:
    """Day-by-day rows, each a list of cells in chronological slot order. Every (day, slot) in
    the requested grid appears, filled or not."""
    by_cell = {(e.day_index, e.slot): e for e in entries}
    ordered_slots = sorted(slots, key=_slot_sort_key)
    rows: list[dict[str, Any]] = []
    for day in range(days):
        cells = []
        for slot in ordered_slots:
            entry = by_cell.get((day, slot))
            card_id = f"slot-{entry.pk}" if entry and entry.pk else f"slot-{day}-{slot}"
            cells.append(
                {
                    "card_id": card_id,
                    "day_index": day,
                    "slot": slot,
                    "slot_label": MealSlot(slot).label,
                    "entry": entry,
                    "reason": reasons.get((day, slot)),
                }
            )
        row_date = start_date + datetime.timedelta(days=day) if start_date else None
        rows.append({"day_index": day, "date": row_date, "cells": cells})
    return rows


def _default_profile(user: Any) -> MealPlanProfile | None:
    qs = MealPlanProfile.objects.filter(owner=user)
    return qs.filter(is_default=True).first() or qs.order_by("name").first()


class PlanIndexView(LoginRequiredMixin, TemplateView):
    """The planner landing page: the user's saved weeks, plus the route into generating a new
    one. A user with no dishes at all gets the empty-state guidance, never a dead Generate
    button (08.14; ``design.md``, "Edge cases")."""

    template_name = "planner/plan_index.html"
    extra_context = {"nav_active": "planner"}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["plans"] = MealPlan.objects.visible_to(user).filter(owner=user)
        context["profiles"] = MealPlanProfile.objects.filter(owner=user).order_by("name")
        context["has_dishes"] = _has_any_dish(user)
        context["has_profile"] = context["profiles"].exists()
        return context


class PlanGenerateView(LoginRequiredMixin, View):
    """``GET`` renders the generate form (profile, start date, days). ``POST`` runs the seeded
    generator and shows an **unsaved** preview grid whose "Save this plan" button carries the
    seed back so "save exactly what I previewed" holds (08.12 carried note)."""

    template_name = "planner/plan_generate.html"

    def _form_context(self, request: HttpRequest, **extra: Any) -> dict[str, Any]:
        user = request.user
        context = {
            "nav_active": "planner",
            "profiles": MealPlanProfile.objects.filter(owner=user).order_by("name"),
            "has_dishes": _has_any_dish(user),
            "default_profile": _default_profile(user),
            "today": datetime.date.today().isoformat(),
            "max_days": MAX_DAYS,
        }
        context.update(extra)
        return context

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, self.template_name, self._form_context(request))

    def post(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        profile = MealPlanProfile.objects.filter(
            owner=user, pk=_int(request.POST.get("profile"))
        ).first()
        if profile is None:
            messages.error(request, "Pick one of your profiles.")
            return render(request, self.template_name, self._form_context(request))

        start_date = _parse_date(request.POST.get("start_date")) or datetime.date.today()
        days = _clamp(_int(request.POST.get("days")) or profile.days, 1, MAX_DAYS)
        seed = _int(request.POST.get("seed"))
        if seed is None or not (0 <= seed <= 2**63 - 1):
            import random

            seed = random.randrange(2**63 - 1)  # noqa: S311 - a plan seed, not a secret (C9)

        result = generate_plan(user, profile, seed=seed, days=days)
        slots = [str(s) for s in (profile.slots or [MealSlot.DINNER.value])]
        filled_count = sum(1 for e in result.entries if e.dish is not None)
        if filled_count == 0:
            # Nothing the planner could place — a new user with no dishes, or a scope /
            # constraint set that leaves it nothing. Guidance, never a blank grid
            # (design.md, "Edge cases").
            return render(
                request,
                self.template_name,
                self._form_context(
                    request,
                    empty_pool=True,
                    profile=profile,
                    empty_pool_reason=result.reasons[0] if result.reasons else None,
                ),
            )

        reasons = {
            (day, slot): reason
            for (day, slot), reason in zip(result.unfilled, result.reasons, strict=True)
        }
        context = self._form_context(
            request,
            preview=True,
            profile=profile,
            start_date=start_date,
            days=days,
            seed=result.seed,
            rows=_grid_rows(
                list(result.entries),
                reasons=reasons,
                days=days,
                slots=slots,
                start_date=start_date,
            ),
            unfilled_count=len(result.unfilled),
            filled_count=filled_count,
        )
        return render(request, self.template_name, context)


class PlanSaveView(LoginRequiredMixin, View):
    """``POST`` — persist the previewed plan. Stateless like the API: re-runs the generator
    from ``{profile, start_date, seed, days}`` (C9 guarantees byte-identical output) and
    saves."""

    def post(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        profile = MealPlanProfile.objects.filter(
            owner=user, pk=_int(request.POST.get("profile"))
        ).first()
        if profile is None:
            messages.error(request, "That profile is no longer available.")
            return redirect("planner:plan-generate")

        start_date = _parse_date(request.POST.get("start_date")) or datetime.date.today()
        days = _clamp(_int(request.POST.get("days")) or profile.days, 1, MAX_DAYS)
        seed = _int(request.POST.get("seed"))
        if seed is None or not (0 <= seed <= 2**63 - 1):
            messages.error(request, "That preview has expired — generate a fresh one.")
            return redirect("planner:plan-generate")

        result = generate_plan(user, profile, seed=seed, days=days)
        plan = save_plan(
            user,
            result,
            profile=profile,
            start_date=start_date,
            name=(request.POST.get("name") or "").strip()[:200],
            days=days,
        )
        messages.success(request, "Plan saved.")
        return redirect(plan.get_absolute_url())


class PlanDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """A saved plan's week grid: one card per day/slot with lock, reroll and manual-swap, the
    profile snapshot summary, and the shopping-list controls."""

    model = MealPlan
    template_name = "planner/plan_detail.html"
    context_object_name = "plan"
    extra_context = {"nav_active": "planner"}

    def get_queryset(self) -> QuerySet[MealPlan]:
        return (
            super()
            .get_queryset()
            .select_related("owner", "profile", "shopping_list")
            .prefetch_related("entries__dish")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        plan = self.object
        user = self.request.user
        entries = list(plan.entries.all())
        visible_ids = set(
            Dish.objects.visible_to(user)
            .filter(pk__in=[e.dish_id for e in entries if e.dish_id])
            .values_list("pk", flat=True)
        )
        for entry in entries:
            entry.dish_visible = entry.dish_id in visible_ids
            entry.is_auto_composed = bool(
                entry.dish and entry.dish.notes == "Auto-composed by the meal planner."
            )
        slots = snapshot_slots(plan)
        context["is_owner"] = plan.owner_id == user.id
        context["rows"] = _grid_rows(
            entries, reasons={}, days=plan.days, slots=slots, start_date=plan.start_date
        )
        context["my_dishes"] = Dish.objects.visible_to(user).order_by("name")
        context["unfilled_count"] = sum(1 for e in entries if e.dish_id is None)
        context["max_days"] = MAX_DAYS
        context["day_choices"] = range(1, MAX_DAYS + 1)
        return context


class _PlanEntryWriteMixin(LoginRequiredMixin, View):
    """Shared setup for the per-slot HTMX actions — resolves an owned plan and one of its
    entries, then re-renders just that slot card."""

    def setup_objects(self, request: HttpRequest, pk: int, entry_pk: int) -> None:
        self.plan = _owned_plan(request, pk)
        self.entry = get_object_or_404(self.plan.entries.select_related("dish"), pk=entry_pk)

    def render_card(self, request: HttpRequest) -> HttpResponse:
        entry = self.entry
        entry.dish_visible = (
            entry.dish_id is None
            or Dish.objects.visible_to(request.user).filter(pk=entry.dish_id).exists()
        )
        entry.is_auto_composed = bool(
            entry.dish and entry.dish.notes == "Auto-composed by the meal planner."
        )
        cell = {
            "card_id": f"slot-{entry.pk}",
            "day_index": entry.day_index,
            "slot": entry.slot,
            "slot_label": MealSlot(entry.slot).label,
            "entry": entry,
            "reason": None,
        }
        return render(
            request,
            "planner/_partials/_slot_card.html",
            {
                "cell": cell,
                "plan": self.plan,
                "is_owner": True,
                "mode": "saved",
                "my_dishes": Dish.objects.visible_to(request.user).order_by("name"),
            },
        )


class PlanEntryLockView(_PlanEntryWriteMixin):
    def post(self, request: HttpRequest, pk: int, entry_pk: int) -> HttpResponse:
        self.setup_objects(request, pk, entry_pk)
        self.entry.is_locked = not self.entry.is_locked
        self.entry.save(update_fields=["is_locked"])
        if request.htmx and not request.htmx_boosted:
            return self.render_card(request)
        return redirect(self.plan.get_absolute_url())


class PlanEntryRerollView(_PlanEntryWriteMixin):
    def post(self, request: HttpRequest, pk: int, entry_pk: int) -> HttpResponse:
        self.setup_objects(request, pk, entry_pk)
        try:
            reroll_entry(self.plan, self.entry)
        except PlannerError as exc:
            messages.error(request, str(exc))
        self.entry.refresh_from_db()
        if request.htmx and not request.htmx_boosted:
            return self.render_card(request)
        return redirect(self.plan.get_absolute_url())


class PlanEntrySwapView(_PlanEntryWriteMixin):
    """Manual swap / clear: set the slot's dish to one the requester can see, or clear it.
    Visibility-checked — attaching a guessed id is the attack (``design.md``, "Security
    notes")."""

    def post(self, request: HttpRequest, pk: int, entry_pk: int) -> HttpResponse:
        self.setup_objects(request, pk, entry_pk)
        raw = (request.POST.get("dish") or "").strip()
        if raw:
            dish = get_object_or_404(Dish.objects.visible_to(request.user), pk=_int(raw))
            self.entry.dish = dish
        else:
            self.entry.dish = None
        self.entry.is_locked = False
        self.entry.save(update_fields=["dish", "is_locked"])
        if request.htmx and not request.htmx_boosted:
            return self.render_card(request)
        return redirect(self.plan.get_absolute_url())


class PlanRegenerateView(LoginRequiredMixin, View):
    """Re-roll every unlocked slot (a fresh seed). Locked slots and their tag budget stand."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        try:
            result = regenerate_plan(plan)
        except PlannerError as exc:
            messages.error(request, str(exc))
            return redirect(plan.get_absolute_url())
        update_plan_in_place(plan, result, seed=result.seed)
        messages.success(request, "Re-rolled the unlocked slots.")
        return redirect(plan.get_absolute_url())


class PlanDaysView(LoginRequiredMixin, View):
    """Change a plan's ``days``. Growing adds unfilled cells immediately; **shrinking drops
    entries**, so ``GET`` first renders a D39-style ``#modal`` confirmation and the drop only
    happens on the confirmed ``POST`` (08.12 carried note; ``design.md``, "Edge cases")."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        days = _clamp(_int(request.GET.get("days")) or plan.days, 1, MAX_DAYS)
        if days == plan.days:
            messages.info(request, f"The plan is already {days} day{'' if days == 1 else 's'}.")
            return redirect(plan.get_absolute_url())
        template = (
            "planner/_partials/_days_confirm.html"
            if request.htmx and not request.htmx_boosted
            else "planner/days_confirm.html"
        )
        dropped = plan.entries.filter(day_index__gte=days).count() if days < plan.days else 0
        return render(
            request,
            template,
            {
                "plan": plan,
                "new_days": days,
                "dropped": dropped,
                "apply_url": reverse("planner:plan-days", args=[plan.pk]),
                "cancel_url": plan.get_absolute_url(),
            },
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        days = _clamp(_int(request.POST.get("days")) or plan.days, 1, MAX_DAYS)
        if days != plan.days:
            plan.days = days
            plan.save(update_fields=["days"])
            reconcile_entries(plan, days=days, slots=snapshot_slots(plan))
            messages.success(request, f"Plan is now {days} day{'' if days == 1 else 's'}.")
        return redirect(plan.get_absolute_url())


class PlanShoppingPreviewView(LoginRequiredMixin, View):
    """``GET`` — the ingredient lines the shopping-list generation would write, with a staples
    toggle and the task-07 warning when regenerating would replace checked items (08.13)."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        raw = request.GET.get("exclude_staples")
        exclude_staples = None if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}
        effective = exclude_staples
        if effective is None:
            effective = plan.profile.exclude_staples if plan.profile else True
        context: dict[str, Any] = {
            "plan": plan,
            "exclude_staples": effective,
            "preview_url": reverse("planner:plan-shopping-preview", args=[plan.pk]),
            "generate_url": reverse("planner:plan-shopping-generate", args=[plan.pk]),
        }
        try:
            preview = preview_shopping_list(plan, exclude_staples=exclude_staples)
        except (ListError, PlannerError) as exc:
            # A planned dish can become invisible between plan save and preview (unshared).
            # Surface it inline, not as a 500 — mirrors the generate view and the API twin.
            context["error"] = str(exc)
            return render(request, "planner/_partials/_shopping_preview.html", context)
        checked_at_risk = 0
        if plan.shopping_list_id is not None:
            checked_at_risk = plan.shopping_list.items.filter(
                is_checked=True, source=ItemSource.GENERATED, generated_from_id=plan.pk
            ).count()
        context.update(
            {
                "lines": preview.lines,
                "staples_skipped": preview.staples_skipped,
                "checked_at_risk": checked_at_risk,
            }
        )
        return render(request, "planner/_partials/_shopping_preview.html", context)


class PlanShoppingGenerateView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        raw = request.POST.get("exclude_staples")
        exclude_staples = None if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}
        try:
            generate_shopping_list(plan, exclude_staples=exclude_staples)
        except (ListError, PlannerError) as exc:
            messages.error(request, str(exc))
            return redirect(plan.get_absolute_url())
        messages.success(request, "Shopping list updated.")
        plan.refresh_from_db()
        return redirect(plan.shopping_list.get_absolute_url())


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _parse_date(value: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


__all__ = [
    "MealPlanProfileForm",
    "PlanDaysView",
    "PlanDetailView",
    "PlanEntryLockView",
    "PlanEntryRerollView",
    "PlanEntrySwapView",
    "PlanGenerateView",
    "PlanIndexView",
    "PlanRegenerateView",
    "PlanSaveView",
    "PlanShoppingGenerateView",
    "PlanShoppingPreviewView",
    "ProfileCreateView",
    "ProfileDeleteView",
    "ProfileListView",
    "ProfileUpdateView",
]
