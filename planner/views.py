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
import random
from decimal import Decimal
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
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
from core.services.graph import GraphError
from core.services.sharing import SharingError, share, unshare
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
from planner.services.candidates import build_candidate_pool
from planner.services.exceptions import PlannerError
from planner.services.generate import generate_plan, regenerate_plan
from planner.services.persist import (
    reconcile_entries,
    reroll_entry,
    save_plan,
    snapshot_slots,
    update_plan_in_place,
)
from planner.services.shopping import (
    generate_shopping_list,
    preview_shopping_list,
    staples_default,
)

User = get_user_model()

_SLOT_ORDER = {slot: index for index, slot in enumerate(MealSlot.values)}


def _slot_sort_key(slot: str) -> int:
    """Chronological meal order (breakfast → lunch → dinner). ``MealPlanEntry.Meta.ordering``
    sorts ``slot`` alphabetically (BREAKFAST, DINNER, LUNCH) — the grid must not inherit that
    (08.12 carried review finding).
    """
    return _SLOT_ORDER.get(slot, len(_SLOT_ORDER))


class TagLimitsWidget(forms.Widget):
    """A repeating "tag + weekly maximum" widget for ``{tag_name: int}`` (N2 — replaces the
    raw JSON textarea). Progressive: a fixed block of rows works with no JS; a small script on
    the profile form reveals an "Add row" button. Serialises straight to / from the dict — an
    all-blank set is ``{}``.
    """

    MIN_ROWS = 3

    def __init__(self, attrs: Any = None) -> None:
        super().__init__(attrs)
        self.tag_names: list[str] = []

    def value_from_datadict(self, data: Any, files: Any, name: str) -> dict[str, str]:
        tags = data.getlist(f"{name}_tag") if hasattr(data, "getlist") else []
        maxes = data.getlist(f"{name}_max") if hasattr(data, "getlist") else []
        result: dict[str, str] = {}
        for tag, raw in zip(tags, maxes, strict=False):
            tag = (tag or "").strip()
            raw = (raw or "").strip()
            if tag and raw:
                result[tag] = raw
        return result

    def _row(self, name: str, tag: str, limit: Any) -> str:
        options = format_html(
            '<option value="">— tag —</option>{}',
            format_html_join(
                "",
                '<option value="{}"{}>{}</option>',
                (
                    (candidate, mark_safe(" selected") if candidate == tag else "", candidate)
                    for candidate in self.tag_names
                ),
            ),
        )
        return format_html(
            '<div class="tag-limit-row">'
            '<select name="{}_tag" aria-label="tag">{}</select>'
            '<input type="number" name="{}_max" min="0" value="{}" aria-label="weekly maximum">'
            '<button type="button" class="btn btn-small btn-icon" data-tag-limits-remove '
            'aria-label="Remove this row" hidden>&times;</button>'
            "</div>",
            name,
            options,
            name,
            "" if limit in (None, "") else limit,
        )

    def render(self, name: str, value: Any, attrs: Any = None, renderer: Any = None) -> str:
        rows = list((value or {}).items())
        while len(rows) < self.MIN_ROWS:
            rows.append(("", ""))
        body = format_html_join("", "{}", ((self._row(name, tag, limit),) for tag, limit in rows))
        widget_id = (attrs or {}).get("id", f"id_{name}")
        add_button = mark_safe(  # noqa: S308 - a static literal, no interpolation
            '<button type="button" class="btn btn-small" data-tag-limits-add hidden>'
            "Add row</button>"
        )
        return format_html(
            '<div class="tag-limits-widget" id="{}" data-tag-limits>{}'
            "<template data-tag-limits-template>{}</template>{}</div>",
            widget_id,
            body,
            self._row(name, "", ""),
            add_button,
        )


class TagLimitsField(forms.Field):
    widget = TagLimitsWidget

    def to_python(self, value: Any) -> dict:
        return value or {}

    def has_changed(self, initial: Any, data: Any) -> bool:
        # ``initial`` comes back from the ``JSONField`` as ``{tag: int}``; ``data`` comes from
        # the widget as ``{tag: str}``. Coerce both to ints so an unchanged, re-bound form
        # does not report itself as changed.
        def _as_ints(value: Any) -> dict[str, int]:
            result: dict[str, int] = {}
            for key, raw in (value or {}).items():
                try:
                    result[key] = int(raw)
                except (TypeError, ValueError):
                    result[key] = raw
            return result

        return _as_ints(initial) != _as_ints(data)


class MealPlanProfileForm(forms.ModelForm):
    """The eight gears as one form.

    ``slots`` is a ``JSONField`` on the model (a list of ``MealSlot`` values); the form exposes
    it as a checkbox group and round-trips it to/from that list. ``tag_limits`` is a repeating
    tag-select + number widget (N2); ``excluded_tags`` / ``excluded_ingredients`` are checkbox
    lists (N3). ``min_rating`` / ``favorites_bias`` clamp rather than error (B5 / B6).
    """

    slots = forms.MultipleChoiceField(
        choices=MealSlot.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Which meals to plan each day.",
    )
    #: Declared plain (not derived from the model field) so the form carries no hard
    #: min/max validator — an out-of-range value is *clamped* in ``clean_*`` rather than
    #: rejected with an error ("saving doesn't work"), the owner's decision on B5 / B6.
    min_rating = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"min": "1", "max": "5", "step": "1"}),
    )
    favorites_bias = forms.DecimalField(
        required=False,
        max_digits=4,
        decimal_places=2,
        initial=MealPlanProfile._meta.get_field("favorites_bias").get_default(),
        widget=forms.NumberInput(attrs={"min": "1", "step": "0.5"}),
    )
    tag_limits = TagLimitsField(required=False)

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
            "excluded_ingredients": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args: Any, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user = user
        tags = list(Tag.objects.order_by("name"))
        self.fields["excluded_tags"].queryset = Tag.objects.order_by("name")
        self.fields["excluded_ingredients"].queryset = Ingredient.objects.visible_to(user).order_by(
            "name"
        )
        self.fields["tag_limits"].widget.tag_names = [tag.name for tag in tags]
        for optional in (
            "min_rating",
            "max_total_minutes",
            "tag_limits",
            "no_repeat_days",
            "favorites_bias",
        ):
            self.fields[optional].required = False

        help_texts = {
            "days": "How many days to plan (1–7).",
            "dish_template": "Balanced, one-pot, or a mix.",
            "source_scope": "Which dishes the planner may choose from.",
            "tag_limits": "Weekly caps by tag — pick a tag and a maximum, e.g. chicken 1.",
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
        raw = self.cleaned_data.get("tag_limits") or {}
        cleaned: dict[str, int] = {}
        for tag, limit in raw.items():
            try:
                number = int(limit)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError("Each weekly maximum must be a whole number.") from exc
            if number < 0:
                raise forms.ValidationError("A weekly maximum cannot be negative.")
            cleaned[tag] = number
        validate_tag_limits(cleaned)  # raises forms.ValidationError on a bad shape
        return cleaned

    def clean_min_rating(self) -> int | None:
        """Silent clamp (B5): blank → ``None`` (gear off), ``< 1`` → 1, ``> 5`` → 5. Never a
        ``ValidationError`` — the owner wants the spinner to save whatever it is given.
        """
        value = self.cleaned_data.get("min_rating")
        if value in (None, ""):
            return None
        return max(1, min(5, value))

    def clean_favorites_bias(self) -> Decimal:
        """Silent clamp (B6): a bias ``< 1`` makes favourites *less* likely, which is
        nonsensical — ``design.md`` says "1 = no bias". Clamp up to 1, no error. A blank
        field falls back to the model default rather than erroring — the column is ``NOT
        NULL`` and the spinner renders pre-filled, so an empty submit means "unchanged".
        """
        value = self.cleaned_data.get("favorites_bias")
        if value in (None, ""):
            return MealPlanProfile._meta.get_field("favorites_bias").get_default()
        if value < 1:
            return Decimal("1")
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
        # Plans shared with the user (and PUBLIC plans) — rendered in a separate read-only
        # "Shared with you" section, outside the owner-only bulk-delete form (B2). Without
        # this a sharee can only reach a shared plan by a hand-typed URL.
        context["shared_plans"] = (
            MealPlan.objects.visible_to(user).exclude(owner=user).select_related("owner")
        )
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
        # Every preview dish came from ``build_candidate_pool`` (``visible_to``-scoped) or was
        # composed from the user's own recipes — all visible by construction. Set the flag the
        # card reads so a real preview dish renders as a link, not "A dish shared privately"
        # (B1).
        for entry in result.entries:
            entry.dish_visible = True
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
        unfilled_count = sum(1 for e in entries if e.dish_id is None)
        context["unfilled_count"] = unfilled_count
        context["max_days"] = MAX_DAYS
        context["day_choices"] = range(1, MAX_DAYS + 1)
        if context["is_owner"]:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(pk=user.pk)
            context["share_url"] = reverse("planner:plan-share", args=[plan.pk])
            context["unshare_url"] = reverse("planner:plan-unshare", args=[plan.pk])
            self._add_unfilled_explanation(context, plan, entries, unfilled_count)
        return context

    def _add_unfilled_explanation(
        self,
        context: dict[str, Any],
        plan: MealPlan,
        entries: list[MealPlanEntry],
        unfilled_count: int,
    ) -> None:
        """A saved plan has no per-slot ``reason`` field (a ``BACKLOG.md`` item), so when it
        has empty slots the owner gets a **page-level** explanation recomputed deterministically
        from the plan's own seed — a banner of the aggregated reasons, or the empty-pool
        guidance when nothing could have been placed at all (B7; ``design.md``, "UI").
        """
        context["empty_pool"] = False
        context["reason_banner"] = []
        if not unfilled_count:
            return
        generic = "This plan's profile was deleted, so its empty slots can't be re-explained."
        if plan.profile is None:
            context["reason_banner"] = [generic]
            return
        try:
            result = regenerate_plan(plan, seed=plan.seed)
        except PlannerError:
            context["reason_banner"] = [generic]
            return
        reasons = list(dict.fromkeys(result.reasons))
        all_unfilled = bool(entries) and unfilled_count == len(entries)
        if all_unfilled and not build_candidate_pool(plan.owner, plan.profile):
            context["empty_pool"] = True
            context["empty_pool_reason"] = reasons[0] if reasons else None
        else:
            context["reason_banner"] = reasons


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
        response = render(
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
        # A per-slot HTMX action swaps only this card, so a flash message raised by the action
        # (a re-roll that found no alternative, say) would never reach ``#messages`` — append
        # the OOB messages fragment the way ``core.mixins.MessageMixin`` does.
        if getattr(request, "htmx", False):
            response.content += render_to_string(
                "_partials/_messages.html", request=request
            ).encode(response.charset or "utf-8")
        return response


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
        before = self.entry.dish_id
        try:
            reroll_entry(self.plan, self.entry)
        except PlannerError as exc:
            messages.info(request, str(exc))
        else:
            self.entry.refresh_from_db()
            if before is not None and self.entry.dish_id == before:
                # Only reachable in theory (a successful reroll_entry excludes the current
                # dish; a failed one raises PlannerError). Guarded on ``before is not None``
                # so deliberately re-rolling an already-empty slot that stays empty does not
                # read as a failure (F3).
                messages.info(request, "Nothing changed — no other dish fits this slot.")
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


class PlanRenameView(LoginRequiredMixin, View):
    """Rename a saved plan (B4). ``GET`` renders a tiny form (bare ``#modal`` fragment for
    HTMX, full page otherwise); ``POST`` writes ``name`` and redirects back. Owner-only via
    ``_owned_plan`` — a sharee gets 403, like every other plan write. A blank name is allowed
    and trimmed: the grid then shows "Meal plan" / the index shows "Untitled plan", exactly as
    a plan generated with no name does."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        template = (
            "planner/_partials/_plan_rename.html"
            if request.htmx and not request.htmx_boosted
            else "planner/plan_rename.html"
        )
        return render(
            request,
            template,
            {
                "plan": plan,
                "apply_url": reverse("planner:plan-rename", args=[plan.pk]),
                "cancel_url": plan.get_absolute_url(),
            },
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        name = (request.POST.get("name") or "").strip()[:200]
        if name != plan.name:
            plan.name = name
            plan.save(update_fields=["name"])
        messages.success(request, "Plan renamed." if name else "Plan name cleared.")
        return redirect(plan.get_absolute_url())


class PlanShoppingPreviewView(LoginRequiredMixin, View):
    """``GET`` — the ingredient lines the shopping-list generation would write, with a staples
    toggle and the task-07 warning when regenerating would replace checked items (08.13)."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        # Tri-state (B4): the toggle sends ``staples_toggle=1`` whenever it is on the page, so
        # an *absent* ``exclude_staples`` with the toggle present is an explicit "include",
        # not "unspecified". Only a request with no toggle at all (the first "Shopping list"
        # click) falls back to the profile / snapshot default.
        if "staples_toggle" in request.GET:
            exclude_staples = request.GET.get("exclude_staples", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            exclude_staples = None
        effective = exclude_staples if exclude_staples is not None else staples_default(plan)
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
        # An explicit "false" from the preview form means "include staples" (B4); a genuinely
        # absent param falls back to the profile / snapshot default inside the service.
        exclude_staples = None if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}
        try:
            generate_shopping_list(plan, exclude_staples=exclude_staples)
        except (ListError, PlannerError) as exc:
            messages.error(request, str(exc))
            return redirect(plan.get_absolute_url())
        messages.success(request, "Shopping list updated.")
        plan.refresh_from_db()
        return redirect(plan.shopping_list.get_absolute_url())


# =====================================================================================
# Delete a plan (B8) and share a plan (B9) — owner-only, mirroring the per-app patterns
# (meals ``_ShareView`` / ``_share_modal.html``; the D39 ``#modal`` confirm for delete).
# =====================================================================================


class PlanDeleteView(LoginRequiredMixin, View):
    """``GET`` renders a D39-style confirmation (bare ``#modal`` fragment for HTMX, full page
    otherwise); ``POST`` deletes the plan. Owner-only via ``_owned_plan``. The plan's entries
    cascade, but its generated shopping ``List`` is a separately-owned object and is left
    untouched (D44)."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        template = (
            "planner/_partials/_plan_confirm_delete.html"
            if request.htmx and not request.htmx_boosted
            else "planner/plan_confirm_delete.html"
        )
        return render(
            request,
            template,
            {
                "plan": plan,
                "object_name": str(plan),
                "apply_url": reverse("planner:plan-delete", args=[plan.pk]),
                "cancel_url": plan.get_absolute_url(),
            },
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        name = str(plan)
        plan.delete()
        messages.success(request, f'Deleted "{name}".')
        return redirect("planner:index")


class PlanBulkDeleteView(LoginRequiredMixin, View):
    """Multi-select delete from the planner index. Every id in the payload is filtered through
    ``MealPlan.objects.visible_to(user).filter(owner=user)`` before anything is removed — an
    id the requester does not own is silently ignored, never an error (B8)."""

    def _owned(self, request: HttpRequest) -> QuerySet[MealPlan]:
        ids = [pk for pk in (_int(raw) for raw in request.POST.getlist("ids")) if pk is not None]
        return MealPlan.objects.visible_to(request.user).filter(owner=request.user, pk__in=ids)

    def post(self, request: HttpRequest) -> HttpResponse:
        plans = list(self._owned(request))
        if not plans:
            messages.info(request, "No plans of yours were selected.")
            return redirect("planner:index")
        if request.POST.get("confirm") != "1":
            return render(
                request,
                "planner/plan_confirm_delete.html",
                {
                    "bulk_plans": plans,
                    "apply_url": reverse("planner:plan-bulk-delete"),
                    "cancel_url": reverse("planner:index"),
                },
            )
        count = len(plans)
        MealPlan.objects.filter(pk__in=[plan.pk for plan in plans]).delete()
        messages.success(request, f"Deleted {count} plan{'' if count == 1 else 's'}.")
        return redirect("planner:index")


class PlanShareModalView(LoginRequiredMixin, View):
    """The shared ``_share_modal.html`` — bare fragment for an ``hx-get`` into ``#modal``, full
    page otherwise. Owner-only via ``_owned_plan`` (a sharee gets 403), matching
    ``PlanDeleteView`` and ``design.md``'s "Share / unshare are owner-only" (F2)."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        context = {
            "object": plan,
            "share_url": reverse("planner:plan-share", args=[plan.pk]),
            "unshare_url": reverse("planner:plan-unshare", args=[plan.pk]),
            "cancel_url": plan.get_absolute_url(),
            "shareable_users": User.objects.filter(is_active=True).exclude(pk=request.user.pk),
        }
        template = (
            "_partials/_share_modal.html"
            if request.htmx and not request.htmx_boosted
            else "planner/plan_share.html"
        )
        return render(request, template, context)


class PlanShareView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        visibility = request.POST.get("visibility") or None
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(is_active=True, pk__in=user_ids))
        try:
            share(plan, actor=request.user, users=target_users, visibility=visibility)
        except (SharingError, GraphError) as exc:
            messages.error(request, str(exc))
            return redirect(plan.get_absolute_url())
        messages.success(request, "Sharing updated.")
        return redirect(plan.get_absolute_url())


class PlanUnshareView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        plan = _owned_plan(request, pk)
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(is_active=True, pk__in=user_ids))
        unshare(plan, actor=request.user, users=target_users)
        messages.success(request, "Access revoked.")
        return redirect(plan.get_absolute_url())


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
    "PlanBulkDeleteView",
    "PlanDaysView",
    "PlanDeleteView",
    "PlanDetailView",
    "PlanEntryLockView",
    "PlanEntryRerollView",
    "PlanEntrySwapView",
    "PlanGenerateView",
    "PlanIndexView",
    "PlanRegenerateView",
    "PlanRenameView",
    "PlanSaveView",
    "PlanShareModalView",
    "PlanShareView",
    "PlanShoppingGenerateView",
    "PlanShoppingPreviewView",
    "PlanUnshareView",
    "ProfileCreateView",
    "ProfileDeleteView",
    "ProfileListView",
    "ProfileUpdateView",
]
