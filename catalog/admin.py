from django.contrib import admin

from catalog.models import Ingredient, Tag, Unit
from core.admin import OwnedModelAdminForm


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


class IngredientAdminForm(OwnedModelAdminForm):
    """The shared ``owner``-XOR-``is_system`` guard (``core.admin.OwnedModelAdminForm``) with
    an explicit field list.

    ``owner``, ``is_system`` and ``visibility`` stay editable here on purpose — the admin is
    where a user's ingredient is promoted to a built-in (MILESTONES.md §8 open question, task
    09) — but ``OwnedModel``'s ``CheckConstraint`` rejects the two impossible combinations at
    the database, and the base ``clean()`` turns those into fixable field errors instead of a
    500 (04.1-04.5 review, finding #10).
    """

    class Meta:
        model = Ingredient
        fields = [
            "name",
            "owner",
            "is_system",
            "visibility",
            "shared_with",
            "default_unit",
            "density_g_per_ml",
            "is_staple",
            "tags",
            "notes",
        ]


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    form = IngredientAdminForm
    list_display = ["name", "owner", "default_unit", "density_g_per_ml", "is_staple", "is_system"]
    list_filter = ["is_staple", "is_system", "visibility", "tags"]
    search_fields = ["name"]
    autocomplete_fields = ["default_unit", "tags"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
    list_select_related = ["owner", "default_unit"]
