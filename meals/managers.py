"""Manager / queryset for ``Dish`` (``Plan/06-Dishes-And-RecipeBooks/design.md``).

Built from ``core.managers.OwnedQuerySet`` (not a bare ``models.Manager``) so ``.visible_to()``
and ``.editable_by()`` compose with ``with_component_graph()`` rather than one replacing the
other (``core/README.md``, "Making a new model owned"). ``core.E002`` requires ``Dish.objects``
to be an ``OwnedManager`` instance, which ``OwnedManager.from_queryset`` preserves.
"""

from __future__ import annotations

from django.db.models import Prefetch

from core.managers import OwnedManager, OwnedQuerySet


class DishQuerySet(OwnedQuerySet):
    def with_component_graph(self) -> DishQuerySet:
        """Prefetch every component, its recipe, and that recipe's full sub-recipe / ingredient
        graph in a bounded number of queries.

        ``meals.services.dishes.flatten_dish`` calls ``recipes.services.flatten.flatten`` once
        per component; without this each component's recipe — and every nested sub-recipe level
        — would be re-fetched (the N+1 ``test_flatten_query_count`` guards against). The recipe
        prefetch reuses ``RecipeQuerySet.with_component_graph()``, which caps the sub-recipe
        chain at ``MAX_DEPTH``.
        """
        from meals.models import DishComponent
        from recipes.models import Recipe

        component_qs = DishComponent.objects.select_related("recipe", "recipe__yield_unit")
        recipe_qs = Recipe.objects.with_component_graph()
        return self.prefetch_related(
            Prefetch("components", queryset=component_qs),
            Prefetch("components__recipe", queryset=recipe_qs),
        )


DishManager = OwnedManager.from_queryset(DishQuerySet)
