"""HTML (HTMX) views for dishes and recipe books (``Plan/06-Dishes-And-RecipeBooks/
design.md``, "UI").

Every screen goes through ``OwnedObjectMixin`` — ``get_queryset()`` scoped to
``.visible_to(request.user)`` and ``IsOwnerOrReadOnly`` gating writes — so template-rendered
screens have no weaker path to owned data than the REST API (``meals/api.py``). Business logic
(flatten, stats, sharing, copy, component authoring) stays in the service layer; these views
parse, call a service, and render.

The REST API is separate — ``meals/api_urls.py`` — the same split ``recipes`` and ``catalog``
use.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from catalog.models import Tag
from core.mixins import HtmxTemplateMixin, OwnedObjectMixin
from core.services.copying import copy_object
from core.services.graph import GraphError
from core.services.sharing import SharingError, share, unshare
from meals.models import BookOrdering, Dish, RecipeBook, RecipeBookEntry
from meals.services.dishes import (
    parse_dish_component_drafts,
    recipe_choices,
    replace_dish_components,
    roles_for,
    total_minutes_for,
)
from meals.services.stats import get_stats, mark_made, set_rating, toggle_favorite
from recipes.models import Recipe, RecipeRole, RecipeStats

User = get_user_model()

_PAGE_SIZE = 24


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


# --- Dish: list -----------------------------------------------------------------------------


class DishListView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, ListView):
    """Card grid of dishes with their component recipes and approximate total time, plus
    debounced search and role / tag / favourite filters. htmx swaps only ``#dish-results``;
    with JavaScript off the same GET form reloads the whole page (design.md, "UI").
    """

    model = Dish
    template_name = "meals/dish_list.html"
    partial_template_name = "meals/_partials/_dish_results.html"
    context_object_name = "dishes"
    paginate_by = _PAGE_SIZE
    extra_context = {"nav_active": "dishes"}

    def get_queryset(self) -> QuerySet[Dish]:
        user = self.request.user
        queryset = (
            super()
            .get_queryset()
            .select_related("owner")
            .prefetch_related("tags", "components__recipe")
        )

        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        role = self.request.GET.get("role", "").strip()
        if role in RecipeRole.values:
            queryset = queryset.filter(components__recipe__role=role).distinct()

        tag_slugs = [slug for slug in self.request.GET.getlist("tags") if slug]
        if tag_slugs:
            queryset = queryset.filter(tags__slug__in=tag_slugs).distinct()

        if _is_true(self.request.GET.get("favorite")):
            queryset = queryset.filter(stats__user=user, stats__is_favorite=True).distinct()

        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        dishes = list(context["dishes"])
        # One page-wide visibility resolution — never the bare, viewer-agnostic
        # ``Dish.total_minutes`` per card (round-2 review finding).
        recipe_ids = {c.recipe_id for d in dishes for c in d.components.all()}
        visible_ids = set(
            Recipe.objects.visible_to(self.request.user)
            .filter(pk__in=recipe_ids)
            .values_list("pk", flat=True)
        )
        for dish in dishes:
            visible = [c.recipe for c in dish.components.all() if c.recipe_id in visible_ids]
            dish.display_minutes = total_minutes_for(visible)
            dish.display_recipes = visible

        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        context["search"] = self.request.GET.get("search", "")
        context["selected_role"] = self.request.GET.get("role", "")
        context["selected_tags"] = [s for s in self.request.GET.getlist("tags") if s]
        context["favorite_only"] = _is_true(self.request.GET.get("favorite"))
        context["all_tags"] = Tag.objects.all()
        context["roles"] = RecipeRole.choices
        context["has_active_filters"] = any(
            (
                context["search"],
                context["selected_role"],
                context["selected_tags"],
                context["favorite_only"],
            )
        )
        return context


# --- Dish: detail ---------------------------------------------------------------------------


class DishDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """Each component recipe with its servings, the combined (flattened, aggregated) ingredient
    list, the "I made this" / rating / favourite widgets, and the task 03 share / copy
    controls. Component recipes the viewer can no longer see are dropped, never leaked (D31).
    """

    model = Dish
    template_name = "meals/dish_detail.html"
    context_object_name = "dish"
    extra_context = {"nav_active": "dishes"}

    def get_queryset(self) -> QuerySet[Dish]:
        return (
            super()
            .get_queryset()
            .select_related("owner", "copied_from", "copied_from__owner")
            .with_component_graph()
            .prefetch_related("tags", "shared_with")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        dish = self.object
        user = self.request.user
        is_owner = user.is_authenticated and dish.owner_id == user.id
        context["is_owner"] = is_owner

        visible_ids = set(
            Recipe.objects.visible_to(user)
            .filter(pk__in=[c.recipe_id for c in dish.components.all()])
            .values_list("pk", flat=True)
        )
        visible_components = [c for c in dish.components.all() if c.recipe_id in visible_ids]
        context["components"] = visible_components
        context["hidden_component_count"] = len(dish.components.all()) - len(visible_components)
        context["combined_ingredients"] = dish.flatten(viewer=user)
        context["total_minutes"] = total_minutes_for([c.recipe for c in visible_components])
        context["roles"] = sorted(roles_for([c.recipe for c in visible_components]))
        context["stats"] = get_stats(user, dish)
        if is_owner:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(pk=user.pk)
        return context


# --- Dish: form -----------------------------------------------------------------------------


class DishForm(forms.ModelForm):
    class Meta:
        model = Dish
        fields = ["name", "description", "tags"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "tags": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["tags"].required = False


def _blank_component_row() -> dict[str, Any]:
    return {"ref": "", "label": "", "servings": "1"}


def _saved_component_rows(dish: Dish) -> list[dict[str, Any]]:
    return [
        {
            "ref": component.recipe_id,
            "label": component.recipe.name,
            "servings": component.servings,
        }
        for component in dish.components.all()
    ]


class _DishEditMixin(LoginRequiredMixin, OwnedObjectMixin):
    """Shared wiring for the create and update dish forms. The scalar fields go through
    ``DishForm``; the component rows are parsed and persisted by ``meals.services.dishes``.
    The dish row and its components are saved in one transaction.
    """

    model = Dish
    form_class = DishForm
    template_name = "meals/dish_form.html"
    extra_context = {"nav_active": "dishes"}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        obj = getattr(self, "object", None)
        if self.request.method == "POST":
            rows = self._submitted_component_rows()
        elif obj is not None:
            rows = _saved_component_rows(obj)
        else:
            rows = []
        context["component_rows"] = rows or [_blank_component_row()]
        return context

    def _submitted_component_rows(self) -> list[dict[str, Any]]:
        post = self.request.POST
        refs = post.getlist("component_recipe")
        servings_values = post.getlist("component_servings")
        rows: list[dict[str, Any]] = []
        for index, ref in enumerate(refs):
            ref = ref.strip()
            rows.append(
                {
                    "ref": ref,
                    "label": self._label_for(ref),
                    "servings": servings_values[index] if index < len(servings_values) else "1",
                }
            )
        return rows

    def _label_for(self, ref: str) -> str:
        if not ref.isdigit():
            return ""
        recipe = Recipe.objects.visible_to(self.request.user).filter(pk=int(ref)).first()
        return recipe.name if recipe is not None else ""

    def _save_dish(self, form: forms.ModelForm) -> HttpResponse:
        dish = form.save(commit=False)
        if not dish.owner_id:
            dish.owner = self.request.user
        try:
            drafts = parse_dish_component_drafts(self.request.POST, user=self.request.user)
            with transaction.atomic():
                dish.save()
                form.save_m2m()
                replace_dish_components(dish, drafts)
        except ValidationError as exc:
            form.add_error(None, exc.messages if hasattr(exc, "messages") else str(exc))
            return self.form_invalid(form)
        self.object = dish
        messages.success(self.request, f'Saved "{dish.name}".')
        return redirect(dish.get_absolute_url())


class DishCreateView(_DishEditMixin, CreateView):
    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        return self._save_dish(form)


class DishUpdateView(_DishEditMixin, UpdateView):
    def get_queryset(self) -> QuerySet[Dish]:
        return super().get_queryset().prefetch_related("components__recipe", "tags")

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        return self._save_dish(form)


class DishDeleteView(LoginRequiredMixin, OwnedObjectMixin, DeleteView):
    model = Dish
    template_name = "meals/dish_confirm_delete.html"
    context_object_name = "dish"
    success_url = reverse_lazy("meals:dish-list")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted {name}.")
        return response


class DishComponentRowView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: one fresh, empty component row for the editor's "add recipe"
    button.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(
            request,
            "meals/_partials/_dish_component_row.html",
            {"row": _blank_component_row()},
        )


class DishRecipeOptionsView(LoginRequiredMixin, View):
    """GET-only HTMX fragment: recipe typeahead results, filtered through ``visible_to`` so a
    private recipe's name is never surfaced (``test_recipe_typeahead_filtered``).
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        query = (request.GET.get("q") or "").strip()
        return render(
            request,
            "meals/_partials/_recipe_options.html",
            {"recipes": recipe_choices(request.user, query), "query": query},
        )


class DishMadeView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        dish = get_object_or_404(Dish.objects.visible_to(request.user), pk=pk)
        mark_made(request.user, dish)
        messages.success(request, f"Logged — you've made {dish.name} before.")
        return redirect(dish.get_absolute_url())


class DishRateView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        dish = get_object_or_404(Dish.objects.visible_to(request.user), pk=pk)
        raw = (request.POST.get("rating") or "").strip()
        rating = None if raw in ("", "0") else _parse_int(raw)
        if raw not in ("", "0") and (rating is None or not (1 <= rating <= 5)):
            messages.error(request, "A rating must be a whole number from 1 to 5.")
            return redirect(dish.get_absolute_url())
        set_rating(request.user, dish, rating)
        messages.success(request, "Rating saved." if rating else "Rating cleared.")
        return redirect(dish.get_absolute_url())


class DishFavoriteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        dish = get_object_or_404(Dish.objects.visible_to(request.user), pk=pk)
        stats = toggle_favorite(request.user, dish)
        messages.success(
            request,
            f"Added {dish.name} to favourites."
            if stats.is_favorite
            else f"Removed {dish.name} from favourites.",
        )
        return redirect(dish.get_absolute_url())


# --- RecipeBook: list ---------------------------------------------------------------------


class RecipeBookListView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, ListView):
    """A shelf-style list of books with their recipe count and description."""

    model = RecipeBook
    template_name = "meals/recipebook_list.html"
    partial_template_name = "meals/_partials/_recipebook_results.html"
    context_object_name = "books"
    paginate_by = _PAGE_SIZE
    extra_context = {"nav_active": "books"}

    def get_queryset(self) -> QuerySet[RecipeBook]:
        queryset = super().get_queryset().select_related("owner").prefetch_related("entries")
        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["querystring"] = params.urlencode()
        context["search"] = self.request.GET.get("search", "")
        return context


# --- RecipeBook: detail -----------------------------------------------------------------


_ORDERING_LABEL = dict(BookOrdering.choices)


def _sorted_book_entries(
    entries: list[RecipeBookEntry], ordering: str, stats_by_recipe: dict[Any, Any]
) -> list[RecipeBookEntry]:
    def key(entry: RecipeBookEntry) -> Any:
        recipe = entry.recipe
        if ordering == BookOrdering.NAME:
            return (recipe.name.lower(),)
        if ordering == BookOrdering.TIME:
            return (recipe.prep_minutes + recipe.cook_minutes, recipe.name.lower())
        if ordering == BookOrdering.RATING:
            row = stats_by_recipe.get(entry.recipe_id)
            rating = row.rating if row and row.rating is not None else -1
            return (-rating, recipe.name.lower())
        if ordering == BookOrdering.TIMES_MADE:
            row = stats_by_recipe.get(entry.recipe_id)
            return (-(row.times_made if row else 0), recipe.name.lower())
        return (entry.position, recipe.name.lower())

    return sorted(entries, key=key)


def _book_detail_context(
    request: HttpRequest, book: RecipeBook, *, ordering: str | None = None
) -> dict[str, Any]:
    """The grouped, ordered sections plus the ordering selector state — shared by the full
    detail page and the reorder / ordering htmx fragments.

    ``ordering`` is an explicit override for callers with no ``?ordering=`` query param (the
    POST ordering endpoint); it falls back to the query param, then the book's stored default.
    """
    user = request.user
    raw_ordering = (ordering or request.GET.get("ordering") or "").strip().upper()
    ordering = raw_ordering if raw_ordering in BookOrdering.values else book.default_ordering

    visible_ids = set(
        Recipe.objects.visible_to(user)
        .filter(pk__in=[e.recipe_id for e in book.entries.all()])
        .values_list("pk", flat=True)
    )
    entries = [e for e in book.entries.all() if e.recipe_id in visible_ids]

    stats_by_recipe: dict[Any, Any] = {}
    if ordering in {BookOrdering.RATING, BookOrdering.TIMES_MADE}:
        stats_by_recipe = {
            row.recipe_id: row
            for row in RecipeStats.objects.filter(
                user=user, recipe_id__in=[e.recipe_id for e in entries]
            )
        }

    grouped: dict[str, list[RecipeBookEntry]] = {}
    section_order: list[str] = []
    for entry in entries:
        if entry.section not in grouped:
            grouped[entry.section] = []
            section_order.append(entry.section)
        grouped[entry.section].append(entry)

    sections = [
        {
            "section": section,
            "entries": _sorted_book_entries(grouped[section], ordering, stats_by_recipe),
            "manual": ordering == BookOrdering.MANUAL,
        }
        for section in section_order
    ]
    return {
        "book": book,
        "sections": sections,
        "recipe_count": len(entries),
        "hidden_entry_count": len(book.entries.all()) - len(entries),
        "ordering": ordering,
        "ordering_choices": BookOrdering.choices,
        "is_owner": user.is_authenticated and book.owner_id == user.id,
    }


class RecipeBookDetailView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, DetailView):
    model = RecipeBook
    template_name = "meals/recipebook_detail.html"
    partial_template_name = "meals/_partials/_book_sections.html"
    context_object_name = "book"
    extra_context = {"nav_active": "books"}

    def get_queryset(self) -> QuerySet[RecipeBook]:
        return (
            super()
            .get_queryset()
            .select_related("owner", "copied_from", "copied_from__owner")
            .prefetch_related("shared_with", "entries__recipe__yield_unit")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(_book_detail_context(self.request, self.object))
        user = self.request.user
        if context["is_owner"]:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(pk=user.pk)
            filed = {e.recipe_id for e in self.object.entries.all()}
            context["addable_recipes"] = [
                r for r in Recipe.objects.visible_to(user).order_by("name") if r.pk not in filed
            ]
            context["sections_in_use"] = sorted(
                {e.section for e in self.object.entries.all() if e.section}
            )
        return context


class RecipeBookForm(forms.ModelForm):
    class Meta:
        model = RecipeBook
        fields = ["name", "description", "default_ordering"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False


class _BookEditMixin(LoginRequiredMixin, OwnedObjectMixin):
    model = RecipeBook
    form_class = RecipeBookForm
    template_name = "meals/recipebook_form.html"
    extra_context = {"nav_active": "books"}

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        book = form.save(commit=False)
        if not book.owner_id:
            book.owner = self.request.user
        book.save()
        form.save_m2m()
        self.object = book
        messages.success(self.request, f'Saved "{book.name}".')
        return redirect(book.get_absolute_url())


class RecipeBookCreateView(_BookEditMixin, CreateView):
    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        return super().form_valid(form)


class RecipeBookUpdateView(_BookEditMixin, UpdateView):
    pass


class RecipeBookDeleteView(LoginRequiredMixin, OwnedObjectMixin, DeleteView):
    model = RecipeBook
    template_name = "meals/recipebook_confirm_delete.html"
    context_object_name = "book"
    success_url = reverse_lazy("meals:book-list")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted {name}.")
        return response


def _owned_book(request: HttpRequest, pk: int) -> RecipeBook:
    """A book the requester **owns** — filing changes (add / remove / reorder) are owner-only,
    exactly as the REST book mutation actions are (``meals/api.py``). An invisible book 404s;
    a book merely shared with the requester 404s here too, since they cannot edit its filing.
    """
    book = get_object_or_404(RecipeBook.objects.visible_to(request.user), pk=pk)
    if book.owner_id != request.user.id:
        raise PermissionDenied("Only the owner can change a book's contents.")
    return book


class BookAddRecipeView(LoginRequiredMixin, View):
    """POST-only. Add a recipe (with an optional section) to a book the requester owns. The
    recipe must be ``visible_to`` the requester — "adding a recipe to a book is the sneakiest
    read primitive in the app" (``design.md``, "Security notes").
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        book = _owned_book(request, pk)
        recipe_pk = _parse_int(request.POST.get("recipe"))
        section = (request.POST.get("section") or "").strip()[:100]
        recipe = None
        if recipe_pk is not None:
            recipe = Recipe.objects.visible_to(request.user).filter(pk=recipe_pk).first()
        if recipe is None:
            messages.error(request, "That recipe is not available to add.")
            return redirect(book.get_absolute_url())
        if RecipeBookEntry.objects.filter(book=book, recipe=recipe).exists():
            messages.info(request, f"{recipe.name} is already in this book.")
            return redirect(book.get_absolute_url())
        existing = [e.position for e in book.entries.all() if e.section == section]
        RecipeBookEntry.objects.create(
            book=book,
            recipe=recipe,
            section=section,
            position=(max(existing) + 1) if existing else 0,
        )
        messages.success(request, f"Added {recipe.name} to {book.name}.")
        return redirect(book.get_absolute_url())


class BookRemoveRecipeConfirmView(LoginRequiredMixin, HtmxTemplateMixin, DetailView):
    """The styled ``#modal`` confirmation for removing a recipe from a book the requester owns
    — the counterpart of ``BookCopyConfirmView``, replacing a raw ``hx-confirm`` prompt. The
    POST target and the no-JS path both stay on ``BookRemoveRecipeView``.

    If the recipe is not actually in the book (a double submit, a stale page), this degrades to
    a redirect back to the book with an info message rather than 500ing.
    """

    model = RecipeBook
    template_name = "meals/recipebook_remove_confirm.html"
    partial_template_name = "meals/_partials/_remove_from_book_confirm.html"
    context_object_name = "book"

    def get_queryset(self) -> QuerySet[RecipeBook]:
        return RecipeBook.objects.visible_to(self.request.user)

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        book = self.get_object()
        if book.owner_id != request.user.id:
            raise PermissionDenied("Only the owner can change a book's contents.")
        self.object = book
        entry = book.entries.select_related("recipe").filter(recipe_id=kwargs["recipe_pk"]).first()
        if entry is None:
            messages.info(request, "That recipe is not in this book.")
            return redirect(book.get_absolute_url())
        context = self.get_context_data(entry=entry)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        entry = kwargs.pop("entry")
        context = super().get_context_data(**kwargs)
        context["recipe"] = entry.recipe
        context["remove_url"] = reverse(
            "meals:book-remove-recipe", args=[self.object.pk, entry.recipe_id]
        )
        context["cancel_url"] = self.object.get_absolute_url()
        return context


class BookRemoveRecipeView(LoginRequiredMixin, HtmxTemplateMixin, View):
    """POST-only. Remove a recipe from a book the requester owns (a filing change, not data
    loss — ``design.md``, "RecipeBook"). Returns the re-rendered ``#book-sections`` fragment
    for an htmx request — with an out-of-band clear of ``#modal`` so the confirm dialog
    dismisses itself — and redirects otherwise.
    """

    def post(self, request: HttpRequest, pk: int, recipe_pk: int) -> HttpResponse:
        book = _owned_book(request, pk)
        deleted, _ = RecipeBookEntry.objects.filter(book=book, recipe_id=recipe_pk).delete()
        if deleted:
            messages.success(request, "Removed from book.")
        book.refresh_from_db()
        if request.htmx and not request.htmx_boosted:
            context = _book_detail_context(request, book)
            context["close_modal"] = True
            return render(request, "meals/_partials/_book_sections.html", context)
        return redirect(book.get_absolute_url())


class BookEntryMoveView(LoginRequiredMixin, HtmxTemplateMixin, View):
    """POST-only. Move an entry up or down within its section, swapping positions with its
    neighbour, then return the re-rendered ``#book-sections`` fragment (or redirect with no
    JavaScript). Touch-friendly up/down — no drag required (task 02 touch-parity rule).
    """

    def post(self, request: HttpRequest, pk: int, recipe_pk: int) -> HttpResponse:
        book = _owned_book(request, pk)
        direction = request.POST.get("direction")
        entry = RecipeBookEntry.objects.filter(book=book, recipe_id=recipe_pk).first()
        if entry is not None and direction in {"up", "down"}:
            siblings = sorted(
                (e for e in book.entries.all() if e.section == entry.section),
                key=lambda e: (e.position, e.recipe_id),
            )
            index = siblings.index(next(e for e in siblings if e.pk == entry.pk))
            swap_with = index - 1 if direction == "up" else index + 1
            if 0 <= swap_with < len(siblings):
                other = siblings[swap_with]
                with transaction.atomic():
                    entry.position, other.position = other.position, entry.position
                    RecipeBookEntry.objects.filter(pk=entry.pk).update(position=entry.position)
                    RecipeBookEntry.objects.filter(pk=other.pk).update(position=other.position)

        book.refresh_from_db()
        if request.htmx and not request.htmx_boosted:
            context = _book_detail_context(request, book)
            return render(request, "meals/_partials/_book_sections.html", context)
        return redirect(book.get_absolute_url())


class BookOrderingView(LoginRequiredMixin, HtmxTemplateMixin, View):
    """POST-only. Persist the chosen ordering as the book's ``default_ordering`` (owner only),
    then re-render the ``#book-sections`` fragment under it — htmx swaps the fragment, a plain
    form POST is the no-JS fallback (``design.md``: "stored as the book's ``default_ordering``
    preference"). POST, not GET, because it writes: a stored preference must not be flippable
    by a cross-site ``<img>`` GET, which CSRF protection does not cover.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        book = get_object_or_404(RecipeBook.objects.visible_to(request.user), pk=pk)
        raw = (request.POST.get("ordering") or "").strip().upper()
        if raw in BookOrdering.values and book.owner_id == request.user.id:
            RecipeBook.objects.filter(pk=book.pk).update(default_ordering=raw)
            book.default_ordering = raw
        if request.htmx and not request.htmx_boosted:
            context = _book_detail_context(request, book, ordering=raw)
            return render(request, "meals/_partials/_book_sections.html", context)
        return redirect(book.get_absolute_url())


class BookCopyConfirmView(LoginRequiredMixin, HtmxTemplateMixin, DetailView):
    """The copy confirmation for a book — always names the recipe count that will be
    deep-copied, and warns above ~20 since it is a slow, heavy operation (``design.md``,
    "Edge cases").
    """

    model = RecipeBook
    template_name = "meals/recipebook_copy_confirm.html"
    partial_template_name = "meals/_partials/_copy_book_confirm.html"
    context_object_name = "book"
    _WARN_ABOVE = 20

    def get_queryset(self) -> QuerySet[RecipeBook]:
        return RecipeBook.objects.visible_to(self.request.user).prefetch_related("entries")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        count = self.object.entries.count()
        context["recipe_count"] = count
        context["warn"] = count > self._WARN_ABOVE
        context["copy_url"] = reverse("meals:book-copy", args=[self.object.pk])
        context["cancel_url"] = self.object.get_absolute_url()
        return context


class BookCopyView(LoginRequiredMixin, View):
    """POST-only. Deep-copies a visible book — and every recipe in it — into a private book the
    requester owns, via the shared copy service (``design.md``, "Sharing and copying").
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        book = get_object_or_404(RecipeBook.objects.visible_to(request.user), pk=pk)
        copy = copy_object(book, actor=request.user)
        messages.success(request, f"Copied {book.name} into your books.")
        return redirect(copy.get_absolute_url())


# --- 06.10: "Add to book" from the recipe detail page ------------------------------------


class RecipeAddToBookView(LoginRequiredMixin, View):
    """POST-only. Files a recipe into one of the requester's own books, from the recipe detail
    page's "Add to book" dropdown. The recipe must be ``visible_to`` the requester.
    """

    def post(self, request: HttpRequest, recipe_pk: int) -> HttpResponse:
        recipe = get_object_or_404(Recipe.objects.visible_to(request.user), pk=recipe_pk)
        book = RecipeBook.objects.filter(
            pk=_parse_int(request.POST.get("book")), owner=request.user
        ).first()
        back = reverse("recipes:recipe-detail", args=[recipe.pk])
        if book is None:
            messages.error(request, "Pick one of your books.")
            return redirect(back)
        if RecipeBookEntry.objects.filter(book=book, recipe=recipe).exists():
            messages.info(request, f"{recipe.name} is already in {book.name}.")
            return redirect(back)
        last = book.entries.filter(section="").order_by("-position").first()
        RecipeBookEntry.objects.create(
            book=book,
            recipe=recipe,
            section="",
            position=(last.position + 1) if last else 0,
        )
        messages.success(request, f"Added {recipe.name} to {book.name}.")
        return redirect(back)


# --- share / unshare (Dish + RecipeBook) -------------------------------------------------


class _ShareModalView(LoginRequiredMixin, OwnedObjectMixin, HtmxTemplateMixin, DetailView):
    """Task 03's ``_share_modal.html`` — full page for a no-JS submit, bare fragment for an
    ``hx-get`` into the detail page's ``#modal`` slot. The modal self-gates on ownership.
    """

    partial_template_name = "_partials/_share_modal.html"
    _share_name: str
    _unshare_name: str
    _detail_name: str

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        pk = self.object.pk
        context["object"] = self.object
        context["share_url"] = reverse(self._share_name, args=[pk])
        context["unshare_url"] = reverse(self._unshare_name, args=[pk])
        context["cancel_url"] = reverse(self._detail_name, args=[pk])
        if self.object.owner_id == self.request.user.id:
            context["shareable_users"] = User.objects.filter(is_active=True).exclude(
                pk=self.request.user.pk
            )
        return context


class DishShareModalView(_ShareModalView):
    model = Dish
    template_name = "meals/dish_share.html"
    _share_name = "meals:dish-share"
    _unshare_name = "meals:dish-unshare"
    _detail_name = "meals:dish-detail"


class RecipeBookShareModalView(_ShareModalView):
    model = RecipeBook
    template_name = "meals/recipebook_share.html"
    _share_name = "meals:book-share"
    _unshare_name = "meals:book-unshare"
    _detail_name = "meals:book-detail"


class _ShareView(LoginRequiredMixin, View):
    model: type
    detail_name: str

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        obj = get_object_or_404(self.model.objects.visible_to(request.user), pk=pk)
        visibility = request.POST.get("visibility") or None
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(is_active=True, pk__in=user_ids))
        try:
            share(obj, actor=request.user, users=target_users, visibility=visibility)
        except (SharingError, GraphError) as exc:
            messages.error(request, str(exc))
            return redirect(reverse(self.detail_name, args=[obj.pk]))
        messages.success(request, "Sharing updated.")
        return redirect(reverse(self.detail_name, args=[obj.pk]))


class _UnshareView(LoginRequiredMixin, View):
    model: type
    detail_name: str

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        obj = get_object_or_404(self.model.objects.visible_to(request.user), pk=pk)
        user_ids = [uid for uid in request.POST.getlist("users") if uid]
        target_users = list(User.objects.filter(pk__in=user_ids))
        unshare(obj, actor=request.user, users=target_users)
        messages.success(request, "Access revoked.")
        return redirect(reverse(self.detail_name, args=[obj.pk]))


class DishShareView(_ShareView):
    model = Dish
    detail_name = "meals:dish-detail"


class DishUnshareView(_UnshareView):
    model = Dish
    detail_name = "meals:dish-detail"


class DishCopyView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        dish = get_object_or_404(Dish.objects.visible_to(request.user), pk=pk)
        copy = copy_object(dish, actor=request.user)
        messages.success(request, f"Copied {dish.name} into your dishes.")
        return redirect(copy.get_absolute_url())


class RecipeBookShareView(_ShareView):
    model = RecipeBook
    detail_name = "meals:book-detail"


class RecipeBookUnshareView(_UnshareView):
    model = RecipeBook
    detail_name = "meals:book-detail"
