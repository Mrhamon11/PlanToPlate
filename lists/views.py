"""HTML (HTMX) views for lists and shopping lists (``Plan/07-Lists-And-Shopping/design.md``,
"UI").

Every screen goes through ``OwnedObjectMixin`` / the ``_owned_list`` helper — ``get_queryset``
scoped to ``.visible_to(request.user)`` and ``IsOwnerOrReadOnly`` gating writes — so a shared
list is **read-only** for the recipient: they can open it but cannot check an item off, add a
line, reorder, or clear it (design.md, "Edge cases"). Collaborative editing is out of scope.

Business logic (aisle grouping, the display decoration that tombstones invisible references,
check/clear/reorder/populate) lives in ``lists.services``; these views parse, call a service,
and render. The REST API is separate — ``lists/api_urls.py``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView

from catalog.models import Unit
from core.mixins import HtmxTemplateMixin, OwnedObjectMixin
from lists.models import ItemSource, List, ListKind
from lists.services import (
    SHOPPING_PAGE_SIZE,
    ListError,
    ListVisibilityError,
    add_dish_to_list,
    add_recipe_to_list,
    annotate_display,
    clear_all,
    clear_checked,
    clear_generated,
    group_by_aisle,
    list_index,
    move_item,
    next_position,
    set_all_checked,
)
from lists.services import set_item_checked as set_item_checked_service
from lists.services import update_item as update_item_service
from meals.models import Dish
from recipes.models import Recipe

_ITEM_PREFETCH = (
    "items__recipe",
    "items__dish",
    "items__ingredient",
    "items__ingredient__tags",
    "items__unit",
)


def _owned_list(request: HttpRequest, pk: int) -> List:
    """A list the requester **owns**. An invisible list 404s; a list merely shared with them
    403s on any write — a shared list is read-only for the recipient (design.md, "Edge cases").
    """
    lst = get_object_or_404(
        List.objects.visible_to(request.user).prefetch_related(*_ITEM_PREFETCH), pk=pk
    )
    if lst.owner_id != request.user.id:
        raise PermissionDenied("A list shared with you is read-only.")
    return lst


def _list_redirect(request: HttpRequest, lst: List) -> HttpResponse:
    """Redirect to ``lst``'s detail page, preserving a ``?page=N`` a no-JS submit carried in
    its form body — so a shopper on page 2 of a long list is not bounced to page 1 after every
    check or add (07.10 follow-up).
    """
    url = lst.get_absolute_url()
    page = (request.POST.get("page") or "").strip()
    if page.isdigit() and int(page) > 1:
        url = f"{url}?page={int(page)}"
    return redirect(url)


def _progress(lst: List) -> dict[str, int]:
    """A fresh count straight from the DB — never the possibly-stale prefetch cache the
    ``_owned_list`` helper loaded before the mutation that triggered this render.
    """
    agg = lst.items.aggregate(total=Count("id"), checked=Count("id", filter=Q(is_checked=True)))
    return {"checked": agg["checked"] or 0, "total": agg["total"] or 0}


# --- list index ---------------------------------------------------------------------------


class ListIndexView(LoginRequiredMixin, HtmxTemplateMixin, TemplateView):
    """Every list the user can see, grouped by kind, with line counts and the default shopping
    list pinned to the top of its group (design.md, "UI": "grouped by kind, item counts, a
    pinned default shopping list").
    """

    template_name = "lists/list_index.html"
    partial_template_name = "lists/_partials/_list_index.html"
    extra_context = {"nav_active": "lists"}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["groups"] = list_index(self.request.user)
        return context


# --- shopping list detail ----------------------------------------------------------------


class ShoppingListDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """The most-used screen on a phone: aisle grouping, sticky progress, one-tap check via
    HTMX, quick-add at the top, generated items styled apart from manual ones. Paginated above
    ``SHOPPING_PAGE_SIZE`` items (design.md, "Edge cases").
    """

    model = List
    template_name = "lists/shopping_detail.html"
    context_object_name = "list"
    extra_context = {"nav_active": "lists"}

    def get_queryset(self) -> QuerySet[List]:
        return super().get_queryset().select_related("owner").prefetch_related(*_ITEM_PREFETCH)

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.object = self.get_object()
        if self.object.kind != ListKind.SHOPPING:
            return redirect("lists:list-detail", pk=self.object.pk)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        lst = self.object
        user = self.request.user

        all_items = list(lst.items.all())
        paginator = Paginator(all_items, SHOPPING_PAGE_SIZE)
        page = paginator.get_page(self.request.GET.get("page"))

        context["is_owner"] = user.is_authenticated and lst.owner_id == user.id
        context["units"] = Unit.objects.all()
        context["aisles"] = group_by_aisle(page.object_list, viewer=user)
        context["progress"] = {
            "checked": sum(1 for i in all_items if i.is_checked),
            "total": len(all_items),
        }
        context["has_generated"] = any(i.source == ItemSource.GENERATED for i in all_items)
        context["page_obj"] = page
        context["paginator"] = paginator
        context["is_paginated"] = page.has_other_pages()
        return context


# --- generic list detail ---------------------------------------------------------------


class GenericListDetailView(LoginRequiredMixin, OwnedObjectMixin, DetailView):
    """A mixed list — free text, recipes, dishes, ingredients — with type icons, inline add of
    text / recipe / dish, and touch up/down reordering (design.md, "UI": "Generic list
    detail").
    """

    model = List
    template_name = "lists/list_detail.html"
    context_object_name = "list"
    extra_context = {"nav_active": "lists"}

    def get_queryset(self) -> QuerySet[List]:
        return super().get_queryset().select_related("owner").prefetch_related(*_ITEM_PREFETCH)

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.object = self.get_object()
        if self.object.kind == ListKind.SHOPPING:
            return redirect("lists:shopping-detail", pk=self.object.pk)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        lst = self.object
        user = self.request.user
        items = list(lst.items.all())
        annotate_display(items, viewer=user)
        context["items"] = items
        context["is_owner"] = user.is_authenticated and lst.owner_id == user.id
        context["units"] = Unit.objects.all()
        context["my_recipes"] = Recipe.objects.visible_to(user).order_by("name")
        context["my_dishes"] = Dish.objects.visible_to(user).order_by("name")
        return context


# --- item mutations (owner only) --------------------------------------------------------


def _render_shopping_item(request: HttpRequest, lst: List, item: Any) -> HttpResponse:
    annotate_display([item], viewer=request.user)
    page = (request.POST.get("page") or "").strip()
    page_number = int(page) if page.isdigit() else 1
    return render(
        request,
        "lists/_partials/_shopping_item.html",
        {
            "item": item,
            "list": lst,
            "is_owner": True,
            "units": Unit.objects.all(),
            "progress": _progress(lst),
            "has_generated": lst.items.filter(source=ItemSource.GENERATED).exists(),
            "page_number": page_number,
        },
    )


class ListItemCheckView(LoginRequiredMixin, View):
    """POST-only. Toggle one item's checked state and return the re-rendered row fragment plus
    an out-of-band refresh of the sticky progress counter (design.md, "UI": "one-tap check via
    HTMX with OOB progress counter update"). No page reload — the core in-the-shop interaction.
    """

    def post(self, request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        item = get_object_or_404(lst.items.all(), pk=item_pk)
        checked = request.POST.get("is_checked") == "true" or (
            "is_checked" not in request.POST and not item.is_checked
        )
        set_item_checked_service(item, is_checked=checked)

        if request.htmx and not request.htmx_boosted:
            return _render_shopping_item(request, lst, item)
        return _list_redirect(request, lst)


class ListItemAddView(LoginRequiredMixin, View):
    """POST-only. Quick-add a line to a list the requester owns — free text, or a reference to
    a recipe / dish they can see. On a ``SHOPPING`` list a dish is expanded to its ingredients;
    on any other kind it stays a single reference line (``lists.services.add_dish_to_list``).

    ``kind`` is honoured literally: ``recipe`` / ``dish`` require a matching valid reference and
    error otherwise — they never silently fall back to whatever is in the text box (07.16).
    Only ``kind == "text"`` (or an unrecognised kind) reads ``text``.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        kind = (request.POST.get("kind") or "text").strip()
        recipe_ref = (request.POST.get("recipe_ref") or "").strip()
        dish_ref = (request.POST.get("dish_ref") or "").strip()

        try:
            if kind == "recipe":
                if not recipe_ref.isdigit():
                    messages.error(request, "Pick a recipe, or switch to free text.")
                else:
                    recipe = get_object_or_404(
                        Recipe.objects.visible_to(request.user), pk=int(recipe_ref)
                    )
                    add_recipe_to_list(lst, recipe, actor=request.user)
                    messages.success(request, f"Added {recipe.name}.")
            elif kind == "dish":
                if not dish_ref.isdigit():
                    messages.error(request, "Pick a dish, or switch to free text.")
                else:
                    dish = get_object_or_404(
                        Dish.objects.visible_to(request.user), pk=int(dish_ref)
                    )
                    add_dish_to_list(lst, dish, actor=request.user)
                    messages.success(request, f"Added {dish.name}.")
            else:
                text = (request.POST.get("text") or "").strip()
                if text:
                    lst.items.create(
                        text=text[:500],
                        position=next_position(lst),
                        source=ItemSource.MANUAL,
                    )
                    messages.success(request, f"Added {text}.")
                else:
                    messages.error(request, "Nothing to add.")
        except (ListError, ListVisibilityError) as exc:
            messages.error(request, str(exc))

        return _list_redirect(request, lst)


class ListItemMoveView(LoginRequiredMixin, View):
    """POST-only. Move an item up or down within a list the requester owns."""

    def post(self, request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        item = get_object_or_404(lst.items.all(), pk=item_pk)
        move_item(lst, item, (request.POST.get("direction") or "").strip())
        return redirect(lst.get_absolute_url())


class ListItemEditView(LoginRequiredMixin, View):
    """POST-only. Override one item's ``quantity`` and ``unit`` (07.23) — an aggregated line is
    often not a buyable amount, so the number is the owner's to correct and the app assumes
    nothing. Owner-only, like every list mutation: a shared list is read-only for the
    recipient. On a shopping list an HTMX request gets the re-rendered row back; otherwise
    (and for no-JS) it redirects, preserving ``?page=``.
    """

    def post(self, request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        item = get_object_or_404(lst.items.all(), pk=item_pk)

        raw_quantity = (request.POST.get("quantity") or "").strip()
        raw_unit = (request.POST.get("unit") or "").strip()

        # Only the ``Decimal()`` parse is guarded here; every quantity rule — finite,
        # non-negative, within the field's digit bounds — lives in ``update_item`` so the REST
        # and HTML paths share one check. A NaN string parses fine, then ``update_item``
        # rejects it before any comparison runs on it.
        quantity: Decimal | None = None
        if raw_quantity:
            try:
                quantity = Decimal(raw_quantity)
            except (InvalidOperation, ValueError):
                messages.error(request, "Enter a number for the quantity.")
                return _list_redirect(request, lst)

        unit = None
        if raw_unit:
            unit = Unit.objects.filter(pk=raw_unit).first() if raw_unit.isdigit() else None
            if unit is None:
                messages.error(request, "That unit is not available.")
                return _list_redirect(request, lst)

        try:
            update_item_service(item, quantity=quantity, unit=unit)
        except ListError as exc:
            messages.error(request, str(exc))
            return _list_redirect(request, lst)

        if request.htmx and not request.htmx_boosted and lst.kind == ListKind.SHOPPING:
            return _render_shopping_item(request, lst, item)
        messages.success(request, "Updated.")
        return _list_redirect(request, lst)


class ListItemDeleteView(LoginRequiredMixin, View):
    """POST-only. Remove one item from a list the requester owns."""

    def post(self, request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        lst.items.filter(pk=item_pk).delete()
        messages.success(request, "Removed.")
        return redirect(lst.get_absolute_url())


class ListClearCheckedView(LoginRequiredMixin, View):
    """POST-only. Bulk-remove every checked item from a list the requester owns."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        removed = clear_checked(lst)
        messages.success(request, f"Cleared {removed} checked item{'' if removed == 1 else 's'}.")
        return redirect(lst.get_absolute_url())


class ListCheckAllView(LoginRequiredMixin, View):
    """POST-only. Check or uncheck **every** item on a list the requester owns in one action.
    Checks by default; unchecks when ``is_checked=false`` is posted — the shopping detail's
    button reads "Check all" until the list is fully checked, then flips to "Uncheck all"
    (07.20). Distinct from "Clear checked", which removes items (07.19).
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        target = request.POST.get("is_checked", "true") != "false"
        count = set_all_checked(lst, is_checked=target)
        verb = "Checked" if target else "Unchecked"
        messages.success(request, f"{verb} {count} item{'' if count == 1 else 's'}.")
        return redirect(lst.get_absolute_url())


class ListClearAllConfirmView(LoginRequiredMixin, HtmxTemplateMixin, DetailView):
    """The styled ``#modal`` confirmation shown before deleting **every** item on a list — a
    destructive, irreversible action, so it mirrors the list-delete confirm pattern: a
    full-page fallback template plus an ``hx-get`` fragment (07.19). The POST target is
    ``ListClearAllView``.
    """

    model = List
    template_name = "lists/clear_all_confirm.html"
    partial_template_name = "lists/_partials/_clear_all_confirm.html"
    context_object_name = "list"

    def get_queryset(self) -> QuerySet[List]:
        return List.objects.visible_to(self.request.user).prefetch_related("items")

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        lst = self.get_object()
        if lst.owner_id != request.user.id:
            raise PermissionDenied("A list shared with you is read-only.")
        self.object = lst
        return self.render_to_response(self.get_context_data())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["item_count"] = len(self.object.items.all())
        context["clear_all_url"] = reverse("lists:clear-all", args=[self.object.pk])
        context["cancel_url"] = self.object.get_absolute_url()
        return context


class ListClearAllView(LoginRequiredMixin, View):
    """POST-only. Delete every item on a list the requester owns (07.19). Reached only through
    ``ListClearAllConfirmView``'s confirm step.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        removed = clear_all(lst)
        messages.success(request, f"Cleared {removed} item{'' if removed == 1 else 's'}.")
        return redirect(lst.get_absolute_url())


class ListRegenerateConfirmView(LoginRequiredMixin, HtmxTemplateMixin, DetailView):
    """The styled ``#modal`` confirmation shown before clearing a shopping list's generated
    items. It **warns** when any generated item is checked, because losing shopping progress
    mid-trip is a genuinely bad surprise (design.md, "Edge cases"). GET renders the confirm;
    the POST target is ``ListRegenerateView``.
    """

    model = List
    template_name = "lists/regenerate_confirm.html"
    partial_template_name = "lists/_partials/_regenerate_confirm.html"
    context_object_name = "list"

    def get_queryset(self) -> QuerySet[List]:
        return List.objects.visible_to(self.request.user).prefetch_related("items")

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        lst = self.get_object()
        if lst.owner_id != request.user.id:
            raise PermissionDenied("A list shared with you is read-only.")
        self.object = lst
        return self.render_to_response(self.get_context_data())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        generated = [
            i
            for i in self.object.items.all()
            if i.source == ItemSource.GENERATED and i.generated_from_id is None
        ]
        context["generated_count"] = len(generated)
        context["checked_count"] = sum(1 for i in generated if i.is_checked)
        context["regenerate_url"] = reverse("lists:regenerate", args=[self.object.pk])
        context["cancel_url"] = self.object.get_absolute_url()
        return context


class ListRegenerateView(LoginRequiredMixin, View):
    """POST-only. Clear the generated (add-dish) lines from a shopping list the requester owns,
    keeping every manual line. Task 08 replaces this with the real "regenerate from the meal
    planner" flow.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        lst = _owned_list(request, pk)
        removed = clear_generated(lst)
        messages.success(request, f"Cleared {removed} generated item{'' if removed == 1 else 's'}.")
        return redirect(lst.get_absolute_url())


# --- list create / delete --------------------------------------------------------------


class ListForm(forms.ModelForm):
    class Meta:
        model = List
        fields = ["name", "kind"]


class ListCreateView(LoginRequiredMixin, OwnedObjectMixin, CreateView):
    model = List
    form_class = ListForm
    template_name = "lists/list_form.html"
    extra_context = {"nav_active": "lists"}

    def form_valid(self, form: forms.ModelForm) -> HttpResponse:
        form.instance.owner = self.request.user
        self.object = form.save()
        messages.success(self.request, f'Created "{self.object.name}".')
        return redirect(self.object.get_absolute_url())


class ListDeleteView(LoginRequiredMixin, OwnedObjectMixin, DeleteView):
    model = List
    template_name = "lists/list_confirm_delete.html"
    context_object_name = "list"
    success_url = reverse_lazy("lists:index")

    def form_valid(self, form: forms.Form) -> HttpResponse:
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted {name}.")
        return response


# --- "Add to list ▾" from recipe and dish detail pages --------------------------------


class AddToListView(LoginRequiredMixin, View):
    """POST-only. Adds a recipe or dish to one of the requester's own lists, from the "Add to
    list ▾" dropdown on the recipe / dish detail page. The object must be ``visible_to`` the
    requester — attaching a guessed id and reading it back is the attack (design.md, "Security
    notes").
    """

    def post(self, request: HttpRequest, kind: str, obj_pk: int) -> HttpResponse:
        model = {"recipe": Recipe, "dish": Dish}.get(kind)
        if model is None:
            raise PermissionDenied("Unknown target.")
        obj = get_object_or_404(model.objects.visible_to(request.user), pk=obj_pk)
        back = obj.get_absolute_url()

        raw = (request.POST.get("list") or "").strip()
        pk = int(raw) if raw.isdigit() else None
        lst = List.objects.filter(pk=pk, owner=request.user).first() if pk is not None else None
        if lst is None:
            messages.error(request, "Pick one of your lists.")
            return redirect(back)

        try:
            if kind == "recipe":
                add_recipe_to_list(lst, obj, actor=request.user)
            else:
                add_dish_to_list(lst, obj, actor=request.user)
        except (ListError, ListVisibilityError) as exc:
            messages.error(request, str(exc))
            return redirect(back)

        expanded = kind == "dish" and lst.kind == ListKind.SHOPPING
        messages.success(
            request,
            f"Added {obj.name}'s ingredients to {lst.name}."
            if expanded
            else f"Added {obj.name} to {lst.name}.",
        )
        return redirect(back)
