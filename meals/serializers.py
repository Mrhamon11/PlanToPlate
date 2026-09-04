"""DRF serializers for the meals API (``Plan/06-Dishes-And-RecipeBooks/design.md``, "API").

``Dish`` and ``RecipeBook`` are both ``OwnedModel``s, so their serializers extend
``core.serializers.OwnedSerializer`` and inherit the read-only ``owner`` / ``visibility`` /
``shared_with`` / ``is_system`` / ``copied_from`` guard and the ``owner``-from-``request.user``
injection on create.

The single most important rule here (``design.md``, "Security notes"): **every referenced
recipe must be ``visible_to`` the requester**, on both nested writes. "Adding a recipe to a
book is the sneakiest read primitive in the app" — an unvalidated recipe ID becomes readable
through the book detail page. Book and dish detail output expand recipes through
``visible_to``, never the raw relation.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import serializers

from core.serializers import OwnedSerializer
from meals.models import Dish, DishComponent, DishStats, RecipeBook, RecipeBookEntry
from meals.services.dishes import roles_for, total_minutes_for
from recipes.models import Recipe


def _visible_recipe_ids(user: Any, recipe_ids: set[Any]) -> set[Any]:
    return set(
        Recipe.objects.visible_to(user).filter(pk__in=recipe_ids).values_list("pk", flat=True)
    )


# --- Dish -------------------------------------------------------------------------------------


class DishComponentSerializer(serializers.ModelSerializer):
    """One recipe within a dish. ``recipe``'s queryset is scoped to what the requester can see
    by the parent ``DishSerializer.__init__`` (which has the request context), so an
    invisible-but-existing id reads as "does not exist" — the same 400 a nonexistent id gives,
    with no enumeration signal between the two (round-2 review finding). ``recipe_name`` is a
    read-only display helper that stays safe even when the related row is not visible to the
    viewer — a name is the documented graceful degradation, never the full row.
    """

    recipe_name = serializers.SerializerMethodField()

    class Meta:
        model = DishComponent
        fields = ["id", "recipe", "recipe_name", "servings", "position"]

    def get_recipe_name(self, obj: DishComponent) -> str | None:
        return obj.recipe.name if obj.recipe_id else None

    def validate_servings(self, value: Any) -> Any:
        if value is not None and value <= 0:
            raise serializers.ValidationError("Servings must be greater than zero.")
        return value


class DishSerializer(OwnedSerializer):
    components = DishComponentSerializer(many=True, required=False)
    total_minutes = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Scope the nested ``recipe`` field to what the requester can see, so a write
        # referencing an invisible id fails identically to one referencing a nonexistent id
        # (round-2 review finding). Only the single-instance write path carries a request in
        # ``__init__``; the ``many=True`` read path attaches its context later and never uses
        # this queryset.
        request = self.context.get("request")
        components_field = self.fields.get("components")
        if request is not None and components_field is not None:
            child = getattr(components_field, "child", components_field)
            child.fields["recipe"].queryset = Recipe.objects.visible_to(request.user)

    class Meta:
        model = Dish
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "components",
            "total_minutes",
            "roles",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _user(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "user", None)

    def _page_visible_recipe_ids(self, obj: Dish) -> set[Any]:
        """The ids of every component recipe on *this page* that the requester can see,
        resolved in **one** query for the whole list rather than one ``visible_to`` per row
        (round-2 review finding: the old per-``obj.pk`` memo did not help across a page).

        Cached on the shared serializer context so the ``ListSerializer`` and all its children
        resolve it once.
        """
        key = "_meals_dish_visible_recipe_ids"
        cache = self.context
        if key not in cache:
            siblings = self.parent.instance if self.parent is not None else None
            dishes = list(siblings) if siblings is not None else [obj]
            recipe_ids = {
                component.recipe_id for dish in dishes for component in dish.components.all()
            }
            cache[key] = _visible_recipe_ids(self._user(), recipe_ids)
        return cache[key]

    def _visible_components(self, obj: Dish) -> list[DishComponent]:
        """The dish's components whose recipe the requester can see, in position order.

        A shared dish can contain a recipe that is no longer visible to a given reader —
        unsharing a child does not cascade back (D31) — and the detail output must drop those
        rather than leak the recipe's name and pk (``design.md``, "Security notes").
        """
        visible = self._page_visible_recipe_ids(obj)
        return [c for c in obj.components.all() if c.recipe_id in visible]

    def get_total_minutes(self, obj: Dish) -> int:
        return total_minutes_for([c.recipe for c in self._visible_components(obj)])

    def get_roles(self, obj: Dish) -> list[str]:
        return sorted(roles_for([c.recipe for c in self._visible_components(obj)]))

    def to_representation(self, instance: Dish) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["components"] = DishComponentSerializer(
            self._visible_components(instance), many=True
        ).data
        return data

    def validate_components(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reject a component whose recipe the requester cannot see — the flagship IDOR
        defence for dishes (``design.md``, "Security notes"). Every referenced recipe is
        resolved in one query, not one per component.
        """
        user = self._user()
        recipes = []
        for component in value:
            recipe = component.get("recipe")
            if recipe is None:
                raise serializers.ValidationError("Each component must reference a recipe.")
            recipes.append(recipe)

        visible = _visible_recipe_ids(user, {recipe.pk for recipe in recipes})
        if any(recipe.pk not in visible for recipe in recipes):
            raise serializers.ValidationError(
                "One of the components references a recipe that is not available to you."
            )
        return value

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Dish:
        components_data = validated_data.pop("components", [])
        dish = super().create(validated_data)
        self._write_components(dish, components_data)
        return dish

    @transaction.atomic
    def update(self, instance: Dish, validated_data: dict[str, Any]) -> Dish:
        components_data = validated_data.pop("components", None)
        dish = super().update(instance, validated_data)
        if components_data is not None:
            dish.components.all().delete()
            self._write_components(dish, components_data)
        return dish

    @staticmethod
    def _write_components(dish: Dish, components_data: list[dict[str, Any]]) -> None:
        for index, data in enumerate(components_data):
            data = {**data}
            data.setdefault("position", index)
            DishComponent.objects.create(dish=dish, **data)


class DishStatsSerializer(serializers.ModelSerializer):
    """The requester's own per-user stats for a dish. ``times_made`` / ``last_made_at`` move
    only through ``POST /made/``; ``PUT /stats/`` sets ``rating`` and ``is_favorite``.
    """

    class Meta:
        model = DishStats
        fields = ["rating", "is_favorite", "times_made", "last_made_at"]
        read_only_fields = ["times_made", "last_made_at"]


# --- RecipeBook ------------------------------------------------------------------------------


class BookRecipeSerializer(serializers.ModelSerializer):
    """A recipe as it appears inside a book listing — enough to render the grid, never the
    full owned row.
    """

    total_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = ["id", "name", "role", "prep_minutes", "cook_minutes", "total_minutes"]

    def get_total_minutes(self, obj: Recipe) -> int:
        return obj.prep_minutes + obj.cook_minutes


class RecipeBookEntrySerializer(serializers.ModelSerializer):
    #: Read-only: entries are created/removed through ``AddRecipeToBookSerializer`` and
    #: ``remove_recipe``, never by deserialising this field.
    recipe = serializers.PrimaryKeyRelatedField(read_only=True)
    recipe_detail = BookRecipeSerializer(source="recipe", read_only=True)

    class Meta:
        model = RecipeBookEntry
        fields = ["id", "recipe", "recipe_detail", "section", "position"]


_ORDERING_ALIASES = {
    "name": "name",
    "rating": "rating",
    "time": "time",
    "times_made": "times_made",
    "manual": "manual",
    "": "manual",
    "NAME": "name",
    "RATING": "rating",
    "TIME": "time",
    "TIMES_MADE": "times_made",
    "MANUAL": "manual",
}


class RecipeBookSerializer(OwnedSerializer):
    """The book, with its entries grouped by ``section`` and sorted within each section by the
    requested (or the book's default) ordering. ``rating`` / ``times_made`` orderings read the
    **requester's** own ``RecipeStats`` rows, so Bob's view of a shared book reflects Bob's
    ratings (``design.md``, "API": ``?ordering=name``).
    """

    sections = serializers.SerializerMethodField()
    recipe_count = serializers.SerializerMethodField()

    class Meta:
        model = RecipeBook
        fields = [
            "id",
            "name",
            "description",
            "default_ordering",
            "sections",
            "recipe_count",
            "owner",
            "visibility",
            "shared_with",
            "is_system",
            "notes",
            "copied_from",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _user(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "user", None)

    def _ordering(self, obj: RecipeBook) -> str:
        request = self.context.get("request")
        raw = None
        if request is not None:
            raw = request.query_params.get("ordering")
        if raw is None:
            raw = obj.default_ordering
        return _ORDERING_ALIASES.get(raw, "manual")

    def _page_visible_recipe_ids(self, obj: RecipeBook) -> set[Any]:
        """The ids of every entry recipe on *this page* that the requester can see, resolved in
        **one** query for the whole list rather than one ``visible_to`` per book (round-2
        review finding). Cached on the shared serializer context.
        """
        key = "_meals_book_visible_recipe_ids"
        cache = self.context
        if key not in cache:
            siblings = self.parent.instance if self.parent is not None else None
            books = list(siblings) if siblings is not None else [obj]
            recipe_ids = {entry.recipe_id for book in books for entry in book.entries.all()}
            cache[key] = _visible_recipe_ids(self._user(), recipe_ids)
        return cache[key]

    def _visible_entries(self, obj: RecipeBook) -> list[RecipeBookEntry]:
        """Entries whose recipe the requester can see — ``get_recipe_count`` and
        ``get_sections`` both need it.
        """
        visible = self._page_visible_recipe_ids(obj)
        return [entry for entry in obj.entries.all() if entry.recipe_id in visible]

    def get_recipe_count(self, obj: RecipeBook) -> int:
        return len(self._visible_entries(obj))

    def get_sections(self, obj: RecipeBook) -> list[dict[str, Any]]:
        entries = self._visible_entries(obj)
        ordering = self._ordering(obj)

        stats_by_recipe: dict[Any, Any] = {}
        if ordering in {"rating", "times_made"}:
            from recipes.models import RecipeStats

            stats_by_recipe = {
                row.recipe_id: row
                for row in RecipeStats.objects.filter(
                    user=self._user(), recipe_id__in=[e.recipe_id for e in entries]
                )
            }

        def sort_key(entry: RecipeBookEntry) -> Any:
            recipe = entry.recipe
            if ordering == "name":
                return (recipe.name.lower(), entry.position)
            if ordering == "time":
                return (recipe.prep_minutes + recipe.cook_minutes, recipe.name.lower())
            if ordering == "rating":
                row = stats_by_recipe.get(entry.recipe_id)
                rating = row.rating if row and row.rating is not None else -1
                return (-rating, recipe.name.lower())
            if ordering == "times_made":
                row = stats_by_recipe.get(entry.recipe_id)
                return (-(row.times_made if row else 0), recipe.name.lower())
            return (entry.position, recipe.name.lower())

        grouped: dict[str, list[RecipeBookEntry]] = {}
        section_order: list[str] = []
        for entry in entries:
            if entry.section not in grouped:
                grouped[entry.section] = []
                section_order.append(entry.section)
            grouped[entry.section].append(entry)

        result: list[dict[str, Any]] = []
        for section in section_order:
            section_entries = sorted(grouped[section], key=sort_key)
            result.append(
                {
                    "section": section,
                    "entries": RecipeBookEntrySerializer(section_entries, many=True).data,
                }
            )
        return result


class AddRecipeToBookSerializer(serializers.Serializer):
    """Body for ``POST /api/recipe-books/<id>/recipes/``. ``recipe``'s queryset is scoped to
    what the requester can see, so an invisible ID reads as "does not exist" rather than
    leaking through the book (``design.md``, "Security notes").
    """

    recipe = serializers.PrimaryKeyRelatedField(queryset=Recipe.objects.none())
    section = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["recipe"].queryset = Recipe.objects.visible_to(user)


class ReorderEntrySerializer(serializers.Serializer):
    recipe = serializers.IntegerField()
    position = serializers.IntegerField(min_value=0)
    section = serializers.CharField(required=False, allow_blank=True, max_length=100)


class ReorderBookSerializer(serializers.Serializer):
    entries = ReorderEntrySerializer(many=True)
