"""Recipe manager / queryset.

Built from ``core.managers.OwnedManager`` (not a bare ``models.Manager``) so ``.visible_to()``
and ``.editable_by()`` compose with the recipe-specific ``with_component_graph()`` rather than
one replacing the other (core/README.md, "Making a new model owned"). ``core.E002`` requires
``Recipe.objects`` to be an ``OwnedManager`` instance, which ``OwnedManager.from_queryset``
preserves.
"""

from __future__ import annotations

from django.db.models import Prefetch

from core.managers import OwnedManager, OwnedQuerySet
from recipes.services.graph import MAX_DEPTH


class RecipeQuerySet(OwnedQuerySet):
    def with_component_graph(self) -> RecipeQuerySet:
        """Prefetch the whole component / ingredient / unit / sub-recipe graph up front, to a
        fixed depth of ``MAX_DEPTH`` sub-recipe levels.

        ``flatten`` walks ``recipe.components`` recursively; without this every component row,
        every ingredient, every unit, and every sub-recipe's own components would be a separate
        query — the N+1 that would make flattening a week of dinners fire hundreds of queries
        (design.md, "Performance"). The depth cap bounds the prefetch chain to a constant
        number of queries regardless of how many components each recipe has.
        """
        from recipes.models import RecipeComponent

        component_qs = RecipeComponent.objects.select_related(
            "ingredient",
            "unit",
            "sub_recipe",
            "sub_recipe__yield_unit",
        )

        prefetches: list[Prefetch] = []
        lookup = "components"
        for _ in range(MAX_DEPTH + 1):
            prefetches.append(Prefetch(lookup, queryset=component_qs))
            lookup = f"{lookup}__sub_recipe__components"

        return self.prefetch_related(*prefetches)


RecipeManager = OwnedManager.from_queryset(RecipeQuerySet)
