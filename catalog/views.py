"""HTML (HTMX) views for the ingredient catalog
(``Plan/04-Units-And-Ingredients/design.md``, "UI"; ``core/README.md`` §5-6 for the owned-model
view wiring).

Every screen goes through ``OwnedObjectMixin`` — ``get_queryset()`` scoped to
``.visible_to(request.user)`` (an invisible ingredient 404s, never 403s), and ``IsOwnerOrReadOnly``
gating writes — so there is no weaker path to owned data than the REST API has. Business logic
(conversion, sharing, copy) stays in the service layer; these views parse, call a service, and
render.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ProtectedError, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from catalog.models import Ingredient, Tag, Unit
from catalog.services.ingredients import owner_has_ingredient_named
from core.exceptions import conflict_from_protected_error
from core.mixins import HtmxTemplateMixin, OwnedObjectMixin
from core.services.copying import copy_object
from core.services.sharing import SharingError, share, unshare

User = get_user_model()

_PAGE_SIZE = 24


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class IngredientForm(forms.ModelForm):
    class Meta:
        model = Ingredient
        fields = ["name", "default_unit", "density_g_per_ml", "is_staple", "tags", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "tags": forms.CheckboxSelectMultiple,
        }
        help_texts = {
            "density_g_per_ml": (
                "Grams per millilitre. Leave blank if you are not sure — a wrong value produces "
                "a confidently wrong shopping list, so blank means 'do not convert' rather than "
                "'assume 1.0'."
            ),
            "is_staple": "Pantry staple (salt, oil, water) — left out of generated shopping lists.",
        }

    def clean_name(self) -> str:
        name = (self.cleaned_data["name"] or "").strip()
        owner = getattr(self.instance, "owner", None)
        if owner is not None and owner_has_ingredient_named(
            owner, name, exclude_pk=self.instance.pk
        ):
            raise forms.ValidationError(f"You already have an ingredient called {name!r}.")
        return name


class IngredientListView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, ListView):
    model = Ingredient
    template_name = "catalog/ingredient_list.html"
    partial_template_name = "catalog/_partials/_ingredient_results.html"
    context_object_name = "ingredients"
    paginate_by = _PAGE_SIZE

    def get_queryset(self) -> QuerySet[Ingredient]:
        # super() is OwnedObjectMixin.get_queryset -> .visible_to(user). Every filter below
        # only narrows it further (test-plan "Security": search must not leak invisible rows).
        queryset = (
            super().get_queryset().select_related("default_unit", "owner").prefetch_related("tags")
        )
        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        tag_slugs = [slug for slug in self.request.GET.getlist("tags") if slug]
        if tag_slugs:
            queryset = queryset.filter(tags__slug__in=tag_slugs).distinct()

        if _is_true(self.request.GET.get("staple")):
            queryset = queryset.filter(is_staple=True)

        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        context["search"] = self.request.GET.get("search", "")
        context["selected_tags"] = [s for s in self.request.GET.getlist("tags") if s]
        context["staple_only"] = _is_true(self.request.GET.get("staple"))
        context["all_tags"] = Tag.objects.all()
        return context


class IngredientDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    model = Ingredient
    template_name = "catalog/ingredient_detail.html"
    context_object_name = "ingredient"

    def get_queryset(self) -> QuerySet[Ingredient]:
        return (
            super()
            .get_queryset()
            .select_related("default_unit", "owner", "copied_from", "copied_from__owner")
            .prefetch_related("tags", "shared_with")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        ingredient = self.object
        is_owner = (
            self.request.user.is_authenticated and ingredient.owner_id == self.request.user.id
        )
        context["is_owner"] = is_owner
        if is_owner:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(
                pk=self.request.user.pk
            )
        return context


class IngredientShareModalView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, DetailView):
    """Renders task 03's ``_share_modal.html`` — as a full page for a no-JS submit, or as the
    bare fragment for an ``hx-get`` into the detail page's ``#modal`` slot (``core/README.md``
    §6). The modal self-gates on ownership; the forms inside post to ``IngredientShareView`` /
    ``IngredientUnshareView``, which redirect back here's ``cancel_url``.
    """

    model = Ingredient
    template_name = "catalog/ingredient_share.html"
    partial_template_name = "_partials/_share_modal.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        pk = self.object.pk
        context["share_url"] = reverse("catalog:ingredient-share", args=[pk])
        context["unshare_url"] = reverse("catalog:ingredient-unshare", args=[pk])
        context["cancel_url"] = reverse("catalog:ingredient-detail", args=[pk])
        context["shareable_users"] = User.objects.filter(is_active=True).exclude(
            pk=self.request.user.pk
        )
        return context


class IngredientCreateView(LoginRequiredMixin, OwnedObjectMixin, CreateView):
    model = Ingredient
    form_class = IngredientForm
    template_name = "catalog/ingredient_form.html"

    def get_form(self, form_class: type[forms.ModelForm] | None = None) -> forms.ModelForm:
        form = super().get_form(form_class)
        # clean_name needs the owner set before validation runs.
        form.instance.owner = self.request.user
        return form

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Added {self.object.name}.")
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["units"] = Unit.objects.all()
        context["is_create"] = True
        return context


class IngredientUpdateView(LoginRequiredMixin, OwnedObjectMixin, UpdateView):
    model = Ingredient
    form_class = IngredientForm
    template_name = "catalog/ingredient_form.html"

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        response = super().form_valid(form)
        messages.success(self.request, f"Saved {self.object.name}.")
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["units"] = Unit.objects.all()
        context["is_create"] = False
        return context


class IngredientDeleteView(LoginRequiredMixin, OwnedObjectMixin, DeleteView):
    model = Ingredient
    template_name = "catalog/ingredient_confirm_delete.html"
    context_object_name = "ingredient"
    success_url = reverse_lazy("catalog:ingredient-list")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        try:
            response = super().form_valid(form)
        except ProtectedError as exc:
            messages.error(self.request, str(conflict_from_protected_error(exc).detail))
            return redirect(self.object.get_absolute_url())
        messages.success(self.request, f"Deleted {name}.")
        return response


class IngredientCopyView(LoginRequiredMixin, View):
    """POST-only. Deep-copies a visible ingredient into a private one the requester owns, via
    the shared copy service — the same code path ``POST /api/ingredients/<id>/copy/`` uses.
    An HTML intermediary (rather than posting straight at the JSON action) so a no-JS submit
    lands back on a real page (``core/README.md`` §6).
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ingredient = get_object_or_404(Ingredient.objects.visible_to(request.user), pk=pk)
        copy = copy_object(ingredient, actor=request.user)
        messages.success(request, f"Copied {ingredient.name} into your catalog.")
        return redirect(copy.get_absolute_url())


class IngredientShareView(LoginRequiredMixin, View):
    """POST-only. Applies a visibility change and/or ``shared_with`` grants through
    ``core.services.sharing.share`` — owner-only, cascade-checked, exactly as the REST
    ``/share/`` action is.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ingredient = get_object_or_404(Ingredient.objects.visible_to(request.user), pk=pk)
        visibility = request.POST.get("visibility") or None
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(is_active=True, pk__in=user_ids))
        # PermissionDenied (non-owner / system object) propagates to the styled 403 page,
        # matching the REST /share/ action's IsOwner gate.
        try:
            share(ingredient, actor=request.user, users=target_users, visibility=visibility)
        except SharingError as exc:
            messages.error(request, str(exc))
            return redirect(ingredient.get_absolute_url())
        messages.success(request, "Sharing updated.")
        return redirect(ingredient.get_absolute_url())


class IngredientUnshareView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ingredient = get_object_or_404(Ingredient.objects.visible_to(request.user), pk=pk)
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(pk__in=user_ids))
        unshare(ingredient, actor=request.user, users=target_users)
        messages.success(request, "Access revoked.")
        return redirect(ingredient.get_absolute_url())


class IngredientQuickAddView(LoginRequiredMixin, View):
    """The task 05 recipe-editor contract (design.md, "UI": "Quick-add"): a minimal-payload
    create that returns a single ``_ingredient_row.html`` fragment, so adding a missing
    ingredient never bounces the cook out of the recipe form. Idempotent on name — re-posting
    an existing name returns that row rather than erroring on the unique constraint.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        name = (request.POST.get("name") or "").strip()
        if not name:
            return render(
                request,
                "catalog/_partials/_ingredient_row.html",
                {"error": "An ingredient name is required."},
                status=400,
            )

        unit = None
        unit_id = request.POST.get("default_unit")
        if unit_id:
            unit = Unit.objects.filter(pk=unit_id).first()
        if unit is None:
            unit = Unit.objects.filter(name="each").first() or Unit.objects.order_by("pk").first()
        if unit is None:
            return render(
                request,
                "catalog/_partials/_ingredient_row.html",
                {"error": "No units are configured yet — run seed_catalog."},
                status=400,
            )

        ingredient = Ingredient.objects.filter(owner=request.user, name__iexact=name).first()
        created = False
        if ingredient is None:
            ingredient = Ingredient.objects.create(
                name=name, owner=request.user, is_system=False, default_unit=unit
            )
            created = True

        return render(
            request,
            "catalog/_partials/_ingredient_row.html",
            {"ingredient": ingredient, "created": created},
            status=201 if created else 200,
        )
