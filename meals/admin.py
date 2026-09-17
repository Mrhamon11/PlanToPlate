"""Admin registration for ``meals`` (task 09.2–09.3).

``DishComponent`` inlines under ``Dish``; ``RecipeBookEntry`` inlines under ``RecipeBook``.
"""

from __future__ import annotations

from django.contrib import admin

from core.admin import OwnedModelAdminForm
from meals.models import (
    Dish,
    DishComponent,
    DishStats,
    RecipeBook,
    RecipeBookEntry,
)


class DishComponentInline(admin.TabularInline):
    model = DishComponent
    fk_name = "dish"
    extra = 0
    raw_id_fields = ["recipe"]


class RecipeBookEntryInline(admin.TabularInline):
    model = RecipeBookEntry
    fk_name = "book"
    extra = 0
    raw_id_fields = ["recipe"]


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    form = OwnedModelAdminForm
    list_display = ["name", "owner", "visibility", "is_system", "updated_at"]
    list_filter = ["visibility", "is_system"]
    search_fields = ["name", "description"]
    autocomplete_fields = ["tags"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
    list_select_related = ["owner"]
    inlines = [DishComponentInline]


@admin.register(DishComponent)
class DishComponentAdmin(admin.ModelAdmin):
    list_display = ["dish", "recipe", "servings", "position"]
    search_fields = ["dish__name", "recipe__name"]
    raw_id_fields = ["dish", "recipe"]
    list_select_related = ["dish", "recipe"]


@admin.register(DishStats)
class DishStatsAdmin(admin.ModelAdmin):
    list_display = ["user", "dish", "rating", "is_favorite", "times_made", "last_made_at"]
    list_filter = ["is_favorite", "rating"]
    search_fields = ["user__username", "dish__name"]
    raw_id_fields = ["user", "dish"]
    list_select_related = ["user", "dish"]


@admin.register(RecipeBook)
class RecipeBookAdmin(admin.ModelAdmin):
    form = OwnedModelAdminForm
    list_display = ["name", "owner", "visibility", "default_ordering", "is_system", "updated_at"]
    list_filter = ["visibility", "default_ordering", "is_system"]
    search_fields = ["name", "description"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
    list_select_related = ["owner"]
    inlines = [RecipeBookEntryInline]


@admin.register(RecipeBookEntry)
class RecipeBookEntryAdmin(admin.ModelAdmin):
    list_display = ["book", "recipe", "section", "position"]
    search_fields = ["book__name", "recipe__name", "section"]
    raw_id_fields = ["book", "recipe"]
    list_select_related = ["book", "recipe"]
