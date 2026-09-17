"""Admin registration for ``recipes`` (task 09.2–09.4, 09 rework).

``RecipeComponentInline`` is the **third** cycle-guard write path (``design.md``: "The recipe
cycle guard must run in the admin too"; task 05's ``test_guard_enforced_on_admin`` was
deferred to 09.4). Its formset ``clean()`` runs the same ``recipes.services.graph`` checks the
serializer and the HTML form already run, so an admin cannot save the corrupt sub-recipe edge
the flattener would later choke on — including on the *add* form, where only the depth cap can
apply (a brand-new recipe cannot close a cycle, but it can still nest past ``MAX_DEPTH``).

``RecipeComponentAdminForm`` guards the **fourth** path — the standalone ``RecipeComponent``
add/change form, whose editable ``recipe`` + ``sub_recipe`` raw-id fields would otherwise let
an admin write exactly that edge directly.

Every admin ``sub_recipe`` write path also runs the sub-recipe **unit-scalability** guard
(09 rework, blocking #1) via ``_ComponentXorCleanMixin`` — the same rule
``recipes/serializers.py`` and ``core/services/importer.py`` enforce, through the one shared
``recipes.services.components.assert_sub_recipe_unit_scalable`` helper. Without it an admin
could save a component whose unit cannot be converted to its sub-recipe's yield unit, and the
flattener (dish detail, shopping-list generation) would 500 on it later.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from core.admin import OwnedModelAdminForm
from recipes.models import Recipe, RecipeComponent, RecipeStats
from recipes.services.components import ComponentError, assert_sub_recipe_unit_scalable
from recipes.services.graph import (
    MAX_DEPTH,
    DepthExceededError,
    GraphError,
    assert_no_cycle,
    recipe_depth,
)


class _ComponentXorCleanMixin:
    """Per-row ``RecipeComponent`` validation shared by the inline form and the standalone
    admin form:

    * the ``ingredient`` XOR ``sub_recipe`` ``CheckConstraint``, turned into a form error
      rather than an ``IntegrityError`` 500 (09.1-09.4 review, non-blocking #1);
    * the sub-recipe unit-scalability guard (09 rework, blocking #1) — a component whose
      ``unit`` cannot be converted to its ``sub_recipe``'s ``yield_unit`` produces a row the
      flattener later 500s on (dish detail, shopping-list generation). This is the same rule
      ``recipes/serializers.py`` and ``core/services/importer.py`` enforce; it runs through
      the one shared helper (``assert_sub_recipe_unit_scalable``), never re-implemented here.

    Both checks are purely per-row, so they live at form level — every inline row is a
    ``RecipeComponentInlineForm`` carrying this mixin, so the inline formset path is covered
    too. The cycle/depth guard, which needs the saved parent and cross-row context, stays in
    ``RecipeComponentInlineFormSet.clean`` / ``RecipeComponentAdminForm.clean``.
    """

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        has_ingredient = cleaned.get("ingredient") is not None
        sub_recipe = cleaned.get("sub_recipe")
        if has_ingredient == (sub_recipe is not None):
            raise ValidationError(
                "A component must reference exactly one of an ingredient or a sub-recipe."
            )
        if sub_recipe is not None:
            quantity = cleaned.get("quantity")
            unit = cleaned.get("unit")
            if quantity is not None and unit is not None:
                try:
                    assert_sub_recipe_unit_scalable(sub_recipe, quantity, unit)
                except ComponentError as exc:
                    raise ValidationError(str(exc)) from exc
        return cleaned


class RecipeComponentInlineForm(_ComponentXorCleanMixin, forms.ModelForm):
    class Meta:
        model = RecipeComponent
        fields = ["ingredient", "sub_recipe", "quantity", "unit", "note", "position"]


class RecipeComponentAdminForm(_ComponentXorCleanMixin, forms.ModelForm):
    """The *standalone* ``RecipeComponent`` add/change form is a fourth ``sub_recipe`` write
    path (alongside the serializer, the HTML form, and ``RecipeComponentInline``). It runs the
    same ``recipes.services.graph`` guard so an admin cannot save a cyclic or over-deep edge
    here that the flattener would only choke on much later (``design.md``: "The recipe cycle
    guard must run in the admin too").
    """

    class Meta:
        model = RecipeComponent
        fields = ["recipe", "ingredient", "sub_recipe", "quantity", "unit", "note", "position"]

    def clean(self) -> dict:
        cleaned = super().clean()
        recipe = cleaned.get("recipe")
        sub_recipe = cleaned.get("sub_recipe")
        if recipe is not None and sub_recipe is not None:
            # ``recipe`` is a required FK on this form, so it always has a pk — the inline
            # formset's ``parent.pk is None`` depth-only branch cannot apply here.
            try:
                assert_no_cycle(recipe, sub_recipe)
            except GraphError as exc:
                raise ValidationError(str(exc)) from exc
        return cleaned


class RecipeComponentInlineFormSet(BaseInlineFormSet):
    """Rejects any inline row whose ``sub_recipe`` would put the parent recipe into a cycle or
    past the depth cap (09.4).

    The per-row sub-recipe unit-scalability guard (09 rework, blocking #1) is enforced one
    level down, in ``RecipeComponentInlineForm.clean`` (``_ComponentXorCleanMixin``) — it
    needs only the single row's fields, so it does not belong in the formset.
    """

    def clean(self) -> None:
        super().clean()
        parent: Recipe = self.instance
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            sub_recipe = form.cleaned_data.get("sub_recipe")
            if sub_recipe is None:
                continue
            if parent.pk is None:
                # A brand-new recipe cannot be referenced by anything yet, so no edge added on
                # the add form can close a loop — and assert_no_cycle's reverse-relation walk
                # needs a saved parent. The depth cap still applies, though: nothing sits above
                # an unsaved parent, so a depth-only check (1 edge + the sub-recipe's own
                # nesting) is exact here and sidesteps the unsaved-instance walk.
                if 1 + recipe_depth(sub_recipe) > MAX_DEPTH:
                    raise ValidationError(
                        str(DepthExceededError([parent.name or "(new recipe)", sub_recipe.name]))
                    )
                continue
            try:
                assert_no_cycle(parent, sub_recipe)
            except GraphError as exc:
                raise ValidationError(str(exc)) from exc


class RecipeComponentInline(admin.TabularInline):
    model = RecipeComponent
    form = RecipeComponentInlineForm
    formset = RecipeComponentInlineFormSet
    fk_name = "recipe"
    extra = 0
    raw_id_fields = ["ingredient", "sub_recipe", "unit"]


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    form = OwnedModelAdminForm
    list_display = [
        "name",
        "owner",
        "role",
        "visibility",
        "yield_quantity",
        "yield_unit",
        "is_system",
        "updated_at",
    ]
    list_filter = ["role", "visibility", "is_system"]
    search_fields = ["name", "description", "instructions"]
    autocomplete_fields = ["yield_unit", "tags"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
    list_select_related = ["owner", "yield_unit"]
    inlines = [RecipeComponentInline]


@admin.register(RecipeComponent)
class RecipeComponentAdmin(admin.ModelAdmin):
    form = RecipeComponentAdminForm
    list_display = ["recipe", "ingredient", "sub_recipe", "quantity", "unit", "position"]
    list_filter = ["unit"]
    search_fields = ["recipe__name", "ingredient__name", "sub_recipe__name", "note"]
    raw_id_fields = ["recipe", "ingredient", "sub_recipe", "unit"]
    list_select_related = ["recipe", "ingredient", "sub_recipe", "unit"]


@admin.register(RecipeStats)
class RecipeStatsAdmin(admin.ModelAdmin):
    list_display = ["user", "recipe", "rating", "is_favorite", "times_made", "last_made_at"]
    list_filter = ["is_favorite", "rating"]
    search_fields = ["user__username", "recipe__name"]
    raw_id_fields = ["user", "recipe"]
    list_select_related = ["user", "recipe"]
