from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

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


class IngredientAdminForm(forms.ModelForm):
    """Turns the owner-XOR-``is_system`` violation into a form error rather than an
    ``IntegrityError`` 500.

    ``owner``, ``is_system`` and ``visibility`` stay editable here on purpose — the admin is
    where a user's ingredient is promoted to a built-in (MILESTONES.md §8 open question, task
    09) — but ``OwnedModel``'s ``CheckConstraint`` rejects the two impossible combinations at
    the database. Validating the same rule in ``clean()`` surfaces it as a field error the
    editor can fix, instead of a stack trace (04.1-04.5 review, finding #10).
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

    def clean(self) -> dict:
        cleaned = super().clean()
        owner = cleaned.get("owner")
        is_system = cleaned.get("is_system")
        if is_system and owner is not None:
            raise ValidationError("A built-in (is_system) ingredient must not have an owner.")
        if not is_system and owner is None:
            raise ValidationError(
                "A non-built-in ingredient must have an owner. Tick 'is system' to make it a "
                "built-in, or pick an owner."
            )
        return cleaned


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    form = IngredientAdminForm
    list_display = ["name", "owner", "default_unit", "density_g_per_ml", "is_staple", "is_system"]
    list_filter = ["is_staple", "is_system", "visibility", "tags"]
    search_fields = ["name"]
    autocomplete_fields = ["default_unit", "tags"]
    raw_id_fields = ["owner", "shared_with"]
    readonly_fields = ["created_at", "updated_at", "copied_from"]
