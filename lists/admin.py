"""Admin registration for ``lists`` (task 09.2–09.3).

``ListItem`` inlines under ``List``. Both carry ``raw_id_fields`` on every content FK — a
``ListItem`` can point at any recipe / dish / ingredient in the database.
"""

from __future__ import annotations

from django.contrib import admin

from core.admin import OwnedModelAdminForm
from lists.models import List, ListItem


class ListItemInline(admin.TabularInline):
    model = ListItem
    fk_name = "list"
    extra = 0
    raw_id_fields = ["recipe", "dish", "ingredient", "unit", "generated_from"]


@admin.register(List)
class ListAdmin(admin.ModelAdmin):
    form = OwnedModelAdminForm
    list_display = [
        "name",
        "owner",
        "kind",
        "visibility",
        "is_default_shopping_list",
        "updated_at",
    ]
    list_filter = ["kind", "visibility", "is_default_shopping_list", "is_system"]
    search_fields = ["name"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
    list_select_related = ["owner"]
    inlines = [ListItemInline]


@admin.register(ListItem)
class ListItemAdmin(admin.ModelAdmin):
    list_display = [
        "list",
        "text",
        "recipe",
        "dish",
        "ingredient",
        "quantity",
        "unit",
        "is_checked",
        "source",
        "position",
    ]
    list_filter = ["source", "is_checked"]
    search_fields = ["text", "list__name"]
    raw_id_fields = ["list", "recipe", "dish", "ingredient", "unit", "generated_from"]
    list_select_related = ["list", "recipe", "dish", "ingredient", "unit"]
