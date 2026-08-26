from django.contrib import admin

from catalog.models import Ingredient, Tag, Unit


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = [
        "abbrev",
        "name",
        "plural",
        "dimension",
        "to_base_factor",
        "count_family",
        "is_system",
    ]
    list_filter = ["dimension", "is_system"]
    search_fields = ["name", "abbrev", "plural"]
    ordering = ["dimension", "to_base_factor"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "slug"]
    list_filter = ["kind"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "default_unit", "density_g_per_ml", "is_staple", "is_system"]
    list_filter = ["is_staple", "is_system", "visibility", "tags"]
    search_fields = ["name"]
    autocomplete_fields = ["default_unit", "tags"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
