"""HTML (HTMX) views for recipes (``Plan/05-Recipes/design.md``, "UI"; ``core/README.md`` §5-6
for the owned-model view wiring).

Every screen goes through ``OwnedObjectMixin`` — ``get_queryset()`` scoped to
``.visible_to(request.user)`` (an invisible recipe 404s, never 403s) and ``IsOwnerOrReadOnly``
gating writes — so template-rendered screens have no weaker path to owned data than the REST
API. Business logic (scaling, flatten, stats, sharing, copy) stays in the service layer; these
views parse, call a service, and render.

The REST API is separate — ``recipes/api_urls.py`` — the same way ``catalog`` splits its two
URL confs.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import F, Prefetch, ProtectedError, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from catalog.models import Ingredient, Tag, Unit
from core.mixins import HtmxTemplateMixin, OwnedObjectMixin
from core.services.copying import copy_object
from core.services.sharing import SharingError, share, unshare
from recipes.models import Recipe, RecipeRole, RecipeStats
from recipes.services.components import (
    ComponentError,
    ingredient_choices,
    parse_component_drafts,
    replace_components,
    sub_recipe_choices,
)
from recipes.services.deletion import conflict_for_protected_recipe
from recipes.services.flatten import scale
from recipes.services.stats import get_stats, mark_made, set_rating, toggle_favorite

User = get_user_model()

_PAGE_SIZE = 24

#: Scale presets offered by the detail page's "cook this for…" control. A free-form factor is
#: still accepted (the REST ``/scaled/`` endpoint has the same contract); these are just the
#: one-tap choices.
SCALE_PRESETS = (Decimal("0.5"), Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"))

_MAX_FACTOR = Decimal(10000)


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_factor(raw: str | None) -> Decimal:
    """``?factor=`` as a ``Decimal`` in ``(0, _MAX_FACTOR]``. Anything non-numeric, non-finite,
    non-positive, or out of range falls back to 1 rather than erroring — the scale control is a
    convenience preview, not a form submission, so a bad value should just show the recipe
    unscaled (the REST ``/scaled/`` endpoint, which is a real API, 400s instead).
    """
    if not raw:
        return Decimal(1)
    try:
        factor = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(1)
    if not factor.is_finite() or factor <= 0 or factor > _MAX_FACTOR:
        return Decimal(1)
    return factor


class RecipeListView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, ListView):
    """Card grid with role/time badges, favourite star and rating, plus debounced search and
    filter chips. htmx swaps only ``#recipe-results``; with JavaScript off the same GET form
    reloads the whole page (design.md, "UI").
    """

    model = Recipe
    template_name = "recipes/recipe_list.html"
    partial_template_name = "recipes/_partials/_recipe_results.html"
    context_object_name = "recipes"
    paginate_by = _PAGE_SIZE

    def get_queryset(self) -> QuerySet[Recipe]:
        user = self.request.user
        # super() -> OwnedObjectMixin.get_queryset -> .visible_to(user). Every filter below only
        # narrows it — none can surface a recipe the viewer cannot already see.
        queryset = (
            super()
            .get_queryset()
            .select_related("yield_unit", "owner")
            .prefetch_related(
                "tags",
                Prefetch(
                    "stats",
                    queryset=RecipeStats.objects.filter(user=user),
                    to_attr="my_stats",
                ),
            )
        )

        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        role = self.request.GET.get("role", "").strip()
        if role in RecipeRole.values:
            queryset = queryset.filter(role=role)

        tag_slugs = [slug for slug in self.request.GET.getlist("tags") if slug]
        if tag_slugs:
            queryset = queryset.filter(tags__slug__in=tag_slugs).distinct()

        max_minutes = _parse_int(self.request.GET.get("max_minutes"))
        if max_minutes is not None:
            queryset = queryset.annotate(
                _total_minutes=F("prep_minutes") + F("cook_minutes")
            ).filter(_total_minutes__lte=max_minutes)

        # min_rating / favourite read the REQUESTER'S own RecipeStats, never the owner's
        # (design.md, "UI"; mirrors recipes.filters.RecipeFilter).
        min_rating = _parse_int(self.request.GET.get("min_rating"))
        if min_rating is not None:
            queryset = queryset.filter(stats__user=user, stats__rating__gte=min_rating).distinct()

        if _is_true(self.request.GET.get("favorite")):
            queryset = queryset.filter(stats__user=user, stats__is_favorite=True).distinct()

        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        context["search"] = self.request.GET.get("search", "")
        context["selected_role"] = self.request.GET.get("role", "")
        context["selected_tags"] = [s for s in self.request.GET.getlist("tags") if s]
        context["max_minutes"] = self.request.GET.get("max_minutes", "")
        context["min_rating"] = self.request.GET.get("min_rating", "")
        context["favorite_only"] = _is_true(self.request.GET.get("favorite"))
        context["all_tags"] = Tag.objects.all()
        context["roles"] = RecipeRole.choices
        context["has_active_filters"] = any(
            (
                context["search"],
                context["selected_role"],
                context["selected_tags"],
                context["max_minutes"],
                context["min_rating"],
                context["favorite_only"],
            )
        )
        return context


class RecipeDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """Ingredients, escaped instructions, the HTMX scale control, sub-recipe expanders, the
    "I made this" / rating / favourite widgets, and the task 03 share / copy controls.
    """

    model = Recipe
    template_name = "recipes/recipe_detail.html"
    context_object_name = "recipe"

    def get_queryset(self) -> QuerySet[Recipe]:
        return (
            super()
            .get_queryset()
            .select_related("yield_unit", "owner", "copied_from", "copied_from__owner")
            .prefetch_related(
                "tags",
                "shared_with",
                "components__ingredient",
                "components__unit",
                "components__sub_recipe",
            )
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        recipe = self.object
        user = self.request.user
        is_owner = user.is_authenticated and recipe.owner_id == user.id
        context["is_owner"] = is_owner
        context["stats"] = get_stats(user, recipe)
        context["scale_presets"] = SCALE_PRESETS
        context["visible_sub_recipe_ids"] = set(
            Recipe.objects.visible_to(user)
            .filter(pk__in=[c.sub_recipe_id for c in recipe.components.all() if c.sub_recipe_id])
            .values_list("pk", flat=True)
        )
        if is_owner:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(pk=user.pk)
        return context


def _default_yield_unit() -> Unit | None:
    """The form's default yield unit. ``design.md`` specifies "4 serving"; the seeded catalog
    has no ``serving`` unit today, so fall back to the generic count unit (``each``). Recorded
    as a deviation in ``Plan/05-Recipes`` — adding a ``serving`` unit to the catalog fixture is
    a catalog-task change, not a recipe-task one.
    """
    return (
        Unit.objects.filter(name="serving").first()
        or Unit.objects.filter(name="each").first()
        or Unit.objects.order_by("pk").first()
    )


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = [
            "name",
            "description",
            "instructions",
            "yield_quantity",
            "yield_unit",
            "prep_minutes",
            "cook_minutes",
            "role",
            "tags",
            "source_url",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "instructions": forms.Textarea(attrs={"rows": 8}),
            "tags": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for name in ("description", "source_url", "prep_minutes", "cook_minutes"):
            self.fields[name].required = False
        if self.instance.pk is None and not self.is_bound:
            self.fields["yield_quantity"].initial = Decimal("4")
            default_unit = _default_yield_unit()
            if default_unit is not None:
                self.fields["yield_unit"].initial = default_unit.pk

    def clean_prep_minutes(self) -> int:
        return self.cleaned_data.get("prep_minutes") or 0

    def clean_cook_minutes(self) -> int:
        return self.cleaned_data.get("cook_minutes") or 0


def _blank_component_row(kind: str = "ingredient") -> dict[str, Any]:
    return {"kind": kind, "ref": "", "label": "", "quantity": "", "unit_id": "", "note": ""}


def _saved_component_rows(recipe: Recipe) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component in recipe.components.all():
        is_sub = bool(component.sub_recipe_id)
        target = component.sub_recipe if is_sub else component.ingredient
        rows.append(
            {
                "kind": "sub_recipe" if is_sub else "ingredient",
                "ref": component.sub_recipe_id if is_sub else component.ingredient_id,
                "label": target.name if target else "",
                "quantity": component.quantity,
                "unit_id": component.unit_id,
                "note": component.note,
            }
        )
    return rows


class _RecipeEditMixin(LoginRequiredMixin, OwnedObjectMixin):
    """Shared wiring for the create and update recipe forms (05.12).

    The scalar fields go through ``RecipeForm``; the component rows are parsed and persisted by
    ``recipes.services.components`` — whose ``replace_components`` routes every sub-recipe
    through ``assert_no_cycle``, so the HTML form is a fully guarded write path
    (``test_guard_enforced_on_form``). The recipe row and its components are saved in one
    transaction: a rejected component set leaves no half-saved recipe behind.
    """

    model = Recipe
    form_class = RecipeForm
    template_name = "recipes/recipe_form.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["units"] = Unit.objects.all()
        obj = getattr(self, "object", None)
        context["edit_recipe_pk"] = obj.pk if obj is not None else ""
        if self.request.method == "POST":
            rows = self._submitted_component_rows()
        elif obj is not None:
            rows = _saved_component_rows(obj)
        else:
            rows = []
        context["component_rows"] = rows or [_blank_component_row()]
        return context

    def _submitted_component_rows(self) -> list[dict[str, Any]]:
        """Rebuild the editor's rows from the raw POST arrays so a validation failure re-renders
        with the cook's work intact (best-effort — the label is re-resolved through
        ``visible_to``)."""
        post = self.request.POST
        kinds = post.getlist("component_kind")
        refs = post.getlist("component_ref")
        quantities = post.getlist("component_quantity")
        units = post.getlist("component_unit")
        notes = post.getlist("component_note")

        rows: list[dict[str, Any]] = []
        for index, raw_kind in enumerate(kinds):
            kind = "sub_recipe" if raw_kind == "sub_recipe" else "ingredient"
            ref = refs[index] if index < len(refs) else ""
            rows.append(
                {
                    "kind": kind,
                    "ref": ref,
                    "label": self._label_for(kind, ref),
                    "quantity": quantities[index] if index < len(quantities) else "",
                    "unit_id": units[index] if index < len(units) else "",
                    "note": notes[index] if index < len(notes) else "",
                }
            )
        return rows

    def _label_for(self, kind: str, ref: str) -> str:
        if not ref.isdigit():
            return ""
        model = Recipe if kind == "sub_recipe" else Ingredient
        obj = model.objects.visible_to(self.request.user).filter(pk=int(ref)).first()
        return obj.name if obj is not None else ""

    def _save_recipe(self, form: forms.ModelForm) -> HttpResponse:
        recipe = form.save(commit=False)
        if not recipe.owner_id:
            recipe.owner = self.request.user
        try:
            drafts = parse_component_drafts(self.request.POST, user=self.request.user)
            with transaction.atomic():
                recipe.save()
                form.save_m2m()
                replace_components(recipe, drafts)
        except ComponentError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        self.object = recipe
        messages.success(self.request, f'Saved "{recipe.name}".')
        return redirect(recipe.get_absolute_url())


class RecipeCreateView(_RecipeEditMixin, CreateView):
    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        return self._save_recipe(form)


class RecipeUpdateView(_RecipeEditMixin, UpdateView):
    def get_queryset(self) -> QuerySet[Recipe]:
        return (
            super()
            .get_queryset()
            .prefetch_related(
                "components__ingredient", "components__sub_recipe", "components__unit", "tags"
            )
        )

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        return self._save_recipe(form)


class RecipeDeleteView(LoginRequiredMixin, OwnedObjectMixin, DeleteView):
    """Owner-only delete with a no-JS confirm page (mirrors ``catalog.IngredientDeleteView``).

    A recipe used as someone's sub-recipe is ``PROTECT``ed at the database level: rather than
    let the ``ProtectedError`` surface as a 500, it becomes a message naming the parents and
    the delete is refused (design.md, "Edge cases": "Deleting a recipe used as a sub-recipe:
    409 naming the parents").
    """

    model = Recipe
    template_name = "recipes/recipe_confirm_delete.html"
    context_object_name = "recipe"
    success_url = reverse_lazy("recipes:recipe-list")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        try:
            response = super().form_valid(form)
        except ProtectedError as exc:
            conflict = conflict_for_protected_recipe(exc, viewer=self.request.user)
            messages.error(self.request, str(conflict.detail))
            return redirect(self.object.get_absolute_url())
        messages.success(self.request, f"Deleted {name}.")
        return response


class RecipeComponentRowView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: one fresh, empty component row for the editor's "add
    ingredient" / "add sub-recipe" buttons (``test_htmx_add_component_row``).
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        kind = "sub_recipe" if request.GET.get("kind") == "sub_recipe" else "ingredient"
        return render(
            request,
            "recipes/_partials/_component_row.html",
            {
                "units": Unit.objects.all(),
                "row": _blank_component_row(kind),
                "recipe_pk": (request.GET.get("recipe") or "").strip(),
            },
        )


class RecipeIngredientOptionsView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: ingredient typeahead results, filtered through ``visible_to`` so
    a private ingredient's name is never surfaced (``test_typeahead_only_returns_visible``).
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        query = (request.GET.get("q") or "").strip()
        return render(
            request,
            "recipes/_partials/_ingredient_options.html",
            {
                "ingredients": ingredient_choices(request.user, query),
                "query": query,
                "quick_add_url": reverse("catalog:ingredient-quick-add"),
            },
        )


class RecipeSubRecipeOptionsView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: sub-recipe typeahead results. Filtered through ``visible_to``
    *and* through ``assert_no_cycle`` — a candidate that would create a cycle is absent from
    the list, not merely rejected on submit (``test_subrecipe_typeahead_excludes_cycles``).
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        query = (request.GET.get("q") or "").strip()
        recipe = None
        raw_pk = (request.GET.get("recipe") or "").strip()
        if raw_pk.isdigit():
            recipe = Recipe.objects.visible_to(request.user).filter(pk=int(raw_pk)).first()
        return render(
            request,
            "recipes/_partials/_subrecipe_options.html",
            {
                "recipes": sub_recipe_choices(request.user, query, recipe=recipe),
                "query": query,
            },
        )


class RecipeScaleView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: the ingredient list with every quantity multiplied by
    ``?factor=``. Reuses ``recipes.services.flatten.scale`` — no business logic here — and
    persists **nothing** (design.md, "UI": "persisting nothing").
    """

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(
            Recipe.objects.visible_to(request.user).prefetch_related(
                "components__ingredient", "components__unit", "components__sub_recipe"
            ),
            pk=pk,
        )
        factor = _parse_factor(request.GET.get("factor"))
        return render(
            request,
            "recipes/_partials/_ingredient_list.html",
            {
                "recipe": recipe,
                "components": scale(recipe, factor),
                "factor": factor,
                "visible_sub_recipe_ids": set(
                    Recipe.objects.visible_to(request.user)
                    .filter(
                        pk__in=[c.sub_recipe_id for c in recipe.components.all() if c.sub_recipe_id]
                    )
                    .values_list("pk", flat=True)
                ),
            },
        )


class RecipeComponentExpandView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: a sub-recipe's own ingredient lines, inlined under the parent
    row without navigating away (design.md, "UI": "a sub-recipe expander").

    Degrades gracefully: if the sub-recipe is somehow not visible to the viewer (a share
    cascade bug), the fragment shows just its name, never its contents or a 500 (design.md,
    "Edge cases").
    """

    def get(self, request: HttpRequest, pk: int, component_pk: int) -> HttpResponse:
        parent = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        component = get_object_or_404(
            parent.components.select_related("sub_recipe"),
            pk=component_pk,
            sub_recipe__isnull=False,
        )
        sub_recipe = (
            Recipe.objects.visible_to(request.user)
            .prefetch_related(
                "components__ingredient", "components__unit", "components__sub_recipe"
            )
            .filter(pk=component.sub_recipe_id)
            .first()
        )
        return render(
            request,
            "recipes/_partials/_subrecipe_expansion.html",
            {
                "component": component,
                "sub_recipe": sub_recipe,
                "sub_recipe_name": component.sub_recipe.name,
            },
        )


class RecipeMadeView(LoginRequiredMixin, View):
    """POST-only. Records that the requester cooked this recipe (``times_made`` += 1,
    ``last_made_at`` stamped) via ``recipes.services.stats.mark_made``.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        mark_made(request.user, recipe)
        messages.success(request, f"Logged — you've made {recipe.name} before.")
        return redirect(_detail_url(recipe))


class RecipeRateView(LoginRequiredMixin, View):
    """POST-only. Sets the requester's 1–5 rating (an empty / ``0`` value clears it)."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        raw = (request.POST.get("rating") or "").strip()
        rating = None if raw in ("", "0") else _parse_int(raw)
        if raw not in ("", "0") and (rating is None or not (1 <= rating <= 5)):
            messages.error(request, "A rating must be a whole number from 1 to 5.")
            return redirect(_detail_url(recipe))
        set_rating(request.user, recipe, rating)
        messages.success(request, "Rating saved." if rating else "Rating cleared.")
        return redirect(_detail_url(recipe))


class RecipeFavoriteView(LoginRequiredMixin, View):
    """POST-only. Flips the requester's favourite flag for this recipe."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        stats = toggle_favorite(request.user, recipe)
        messages.success(
            request,
            f"Added {recipe.name} to favourites."
            if stats.is_favorite
            else f"Removed {recipe.name} from favourites.",
        )
        return redirect(_detail_url(recipe))


class RecipePrintView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """A standalone ink-light page for cooking from paper (05.13). Its own minimal document —
    it does not extend ``base.html`` — and links ``static/css/print.css``.
    """

    model = Recipe
    template_name = "recipes/recipe_print.html"
    context_object_name = "recipe"

    def get_queryset(self) -> QuerySet[Recipe]:
        # with_component_graph() prefetches every sub-recipe level so the print page can list a
        # sub-recipe's own ingredients inline without an N+1 (design.md, "UI": "People cook from
        # paper" — a sub-recipe printed as one opaque line is not something you can shop or cook
        # from).
        return (
            super()
            .get_queryset()
            .select_related("yield_unit")
            .with_component_graph()
            .prefetch_related("tags")
        )


class RecipeShareModalView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, DetailView):
    """Task 03's ``_share_modal.html`` — full page for a no-JS submit, bare fragment for an
    ``hx-get`` into the detail page's ``#modal`` slot. The modal self-gates on ownership.
    """

    model = Recipe
    template_name = "recipes/recipe_share.html"
    partial_template_name = "_partials/_share_modal.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        pk = self.object.pk
        context["share_url"] = reverse("recipes:recipe-share", args=[pk])
        context["unshare_url"] = reverse("recipes:recipe-unshare", args=[pk])
        context["cancel_url"] = reverse("recipes:recipe-detail", args=[pk])
        # Only the owner ever sees a populated modal (the partial self-gates on ownership), so
        # only the owner needs the candidate list built — mirrors RecipeDetailView.
        if self.object.owner_id == self.request.user.id:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(
                pk=self.request.user.pk
            )
        return context


class RecipeShareView(LoginRequiredMixin, View):
    """POST-only. Applies a visibility change and/or ``shared_with`` grants through
    ``core.services.sharing.share`` — owner-only, cascade-checked, exactly as the REST
    ``/share/`` action is.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        visibility = request.POST.get("visibility") or None
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(is_active=True, pk__in=user_ids))
        try:
            share(recipe, actor=request.user, users=target_users, visibility=visibility)
        except SharingError as exc:
            messages.error(request, str(exc))
            return redirect(_detail_url(recipe))
        messages.success(request, "Sharing updated.")
        return redirect(_detail_url(recipe))


class RecipeUnshareView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(pk__in=user_ids))
        unshare(recipe, actor=request.user, users=target_users)
        messages.success(request, "Access revoked.")
        return redirect(_detail_url(recipe))


class RecipeCopyView(LoginRequiredMixin, View):
    """POST-only. Deep-copies a visible recipe (and its whole sub-recipe tree) into a private
    one the requester owns, via the shared copy service — the same path
    ``POST /api/recipes/<id>/copy/`` uses.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=pk)
        copy = copy_object(recipe, actor=request.user)
        messages.success(request, f"Copied {recipe.name} into your recipes.")
        return redirect(_detail_url(copy))


def _detail_url(recipe: Recipe) -> str:
    return reverse("recipes:recipe-detail", args=[recipe.pk])


__all__ = [
    "RecipeComponentExpandView",
    "RecipeComponentRowView",
    "RecipeCopyView",
    "RecipeCreateView",
    "RecipeDeleteView",
    "RecipeDetailView",
    "RecipeFavoriteView",
    "RecipeIngredientOptionsView",
    "RecipeListView",
    "RecipeMadeView",
    "RecipePrintView",
    "RecipeRateView",
    "RecipeScaleView",
    "RecipeShareModalView",
    "RecipeShareView",
    "RecipeSubRecipeOptionsView",
    "RecipeUnshareView",
    "RecipeUpdateView",
]
