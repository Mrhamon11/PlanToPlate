"""Admin registration for ``planner`` (task 09.2–09.3).

``MealPlanEntry`` inlines under ``MealPlan``. ``profile_snapshot`` is server-generated and
shown read-only.
"""

from __future__ import annotations

from django.contrib import admin

from core.admin import OwnedModelAdminForm
from planner.models import MealPlan, MealPlanEntry, MealPlanProfile


class MealPlanEntryInline(admin.TabularInline):
    model = MealPlanEntry
    fk_name = "plan"
    extra = 0
    raw_id_fields = ["dish"]


@admin.register(MealPlanProfile)
class MealPlanProfileAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "owner",
        "is_default",
        "dish_template",
        "source_scope",
        "days",
    ]
    list_filter = ["dish_template", "source_scope", "is_default", "favorites_only"]
    search_fields = ["name", "owner__username"]
    raw_id_fields = ["owner"]
    autocomplete_fields = ["excluded_tags", "excluded_ingredients"]
    readonly_fields = ["created_at", "updated_at"]
    list_select_related = ["owner"]


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    form = OwnedModelAdminForm
    list_display = ["__str__", "owner", "start_date", "days", "visibility", "created_at"]
    list_filter = ["visibility", "start_date", "is_system"]
    search_fields = ["name", "owner__username"]
    raw_id_fields = ["owner", "shared_with", "profile", "shopping_list"]
    readonly_fields = ["created_at", "updated_at", "copied_from", "profile_snapshot"]
    list_select_related = ["owner"]
    inlines = [MealPlanEntryInline]


@admin.register(MealPlanEntry)
class MealPlanEntryAdmin(admin.ModelAdmin):
    list_display = ["plan", "day_index", "slot", "dish", "is_locked"]
    list_filter = ["slot", "is_locked"]
    search_fields = ["plan__name", "dish__name"]
    raw_id_fields = ["plan", "dish"]
    list_select_related = ["plan", "dish"]
