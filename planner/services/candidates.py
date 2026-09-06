"""The candidate pool — every dish the generator is allowed to pick from for one user under
one profile (``Plan/08-Meal-Planner/design.md``, "Algorithm", step 1).

**Security.** The pool starts from ``Dish.objects.visible_to(user)`` and never widens. *"A
planner that suggests a dish you cannot see is a data leak wearing a friendly hat"* — the
scope narrowing below can only ever remove dishes from that set, never add one.

**Bounded.** The per-dish checks that cannot be a plain database filter — the total-time
budget, and the exclusion of a dish whose *flattened* ingredient set (sub-recipes included)
contains an excluded ingredient — run in Python over a fixed number of prefetched batches: the
components (with their recipe), the tags, and, only when an ingredient exclusion is set, one
``with_component_graph`` batch of the component recipes keyed by id. The query count does not
grow with the number of dishes.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db.models import Prefetch, Q
from django.utils import timezone

from meals.models import Dish, DishComponent, DishStats
from meals.services.dishes import total_minutes_for
from planner.models import SourceScope
from recipes.models import Recipe
from recipes.services.graph import MAX_DEPTH

if TYPE_CHECKING:
    from planner.models import MealPlanProfile


def build_candidate_pool(user: object, profile: MealPlanProfile) -> list[Dish]:
    """The dishes ``user`` may be served under ``profile``, ordered by ``pk`` for a stable,
    reproducible generator.

    Each dish comes back with its components (and their recipes) and tags prefetched, so the
    generator can read roles, total time and tags without another query.
    """
    scoped = _scoped_queryset(user, profile)

    candidate_ids = list(scoped.values_list("pk", flat=True))
    excluded_tag_ids = set(profile.excluded_tags.values_list("pk", flat=True))
    if excluded_tag_ids:
        candidate_ids = list(scoped.exclude(tags__in=excluded_tag_ids).values_list("pk", flat=True))

    stats_by_dish = {
        row.dish_id: row for row in DishStats.objects.filter(user=user, dish_id__in=candidate_ids)
    }
    cutoff = timezone.now() - timedelta(days=profile.no_repeat_days)
    surviving_ids = [
        dish_id
        for dish_id in candidate_ids
        if _passes_stats_gates(stats_by_dish.get(dish_id), profile, cutoff)
    ]

    dishes = list(
        Dish.objects.filter(pk__in=surviving_ids)
        .prefetch_related(
            Prefetch(
                "components",
                queryset=DishComponent.objects.select_related("recipe").order_by("position"),
            ),
            "tags",
        )
        .order_by("pk")
    )

    excluded_ingredient_ids = set(profile.excluded_ingredients.values_list("pk", flat=True))
    recipe_graph = _recipe_graph(dishes) if excluded_ingredient_ids else {}

    pool: list[Dish] = []
    for dish in dishes:
        component_recipes = [component.recipe for component in dish.components.all()]
        if (
            profile.max_total_minutes is not None
            and total_minutes_for(component_recipes) > profile.max_total_minutes
        ):
            continue
        if excluded_ingredient_ids and (
            _flattened_ingredient_ids(dish, recipe_graph) & excluded_ingredient_ids
        ):
            continue
        pool.append(dish)
    return pool


def explain_empty_pool(user: object, profile: MealPlanProfile) -> str:
    """A human-readable cause for a pool that came back empty — the generator stamps this on
    every unfilled slot (``design.md``, "Edge cases"). Distinguishes the new-user path ("you
    have no dishes yet") from over-tight constraints, and calls out ``no_repeat_days`` when it
    is the filter that emptied a non-empty library.
    """
    in_scope = _scoped_queryset(user, profile).count()
    if in_scope == 0:
        if Dish.objects.visible_to(user).filter(components__isnull=False).exists():
            return (
                "None of your dishes are in this profile's source scope — widen the scope to "
                "include shared or public dishes."
            )
        return "You have no dishes yet — create one or copy a public one."

    if profile.no_repeat_days:
        # A shallow copy with the window widened to nothing — reads the same rows, saves
        # nothing, leaves the caller's profile untouched.
        relaxed = copy.copy(profile)
        relaxed.no_repeat_days = 0
        if build_candidate_pool(user, relaxed):
            return (
                f"Every dish in scope was cooked within the last {profile.no_repeat_days} "
                "days; lower the no-repeat window."
            )
    return (
        "No dish matches every constraint (rating, favourites, time budget and exclusions "
        "combined). Loosen one of them."
    )


def _recipe_graph(dishes: list[Dish]) -> dict[int, Recipe]:
    """Every component recipe across ``dishes``, loaded once with its full sub-recipe graph and
    keyed by id — the ``populate_shopping_list`` pattern (``lists/services.py``): look recipes
    up by ``component.recipe_id``, never through ``component.recipe``, so the deep prefetch is
    one batch rather than one per dish.
    """
    recipe_ids = {component.recipe_id for dish in dishes for component in dish.components.all()}
    return {
        recipe.pk: recipe
        for recipe in Recipe.objects.with_component_graph().filter(pk__in=recipe_ids)
    }


def _passes_stats_gates(stats: DishStats | None, profile: MealPlanProfile, cutoff) -> bool:
    if profile.min_rating is not None and (
        stats is None or (stats.rating or 0) < profile.min_rating
    ):
        return False
    if profile.favorites_only and (stats is None or not stats.is_favorite):
        return False
    if (
        profile.no_repeat_days
        and stats is not None
        and stats.last_made_at is not None
        and stats.last_made_at >= cutoff
    ):
        return False
    return True


def _scoped_queryset(user: object, profile: MealPlanProfile):
    """``visible_to(user)`` narrowed to the profile's source scope and to dishes that actually
    have components. ``PUBLIC`` keeps the full visible set; tighter scopes intersect it.
    """
    queryset = Dish.objects.visible_to(user)
    scope = profile.source_scope
    if scope == SourceScope.MINE:
        queryset = queryset.filter(owner=user)
    elif scope == SourceScope.SHARED:
        queryset = queryset.filter(Q(owner=user) | Q(shared_with=user))
    return queryset.filter(components__isnull=False).distinct()


def _flattened_ingredient_ids(dish: Dish, recipe_graph: dict[int, Recipe]) -> set[int]:
    """Every ingredient id reachable from ``dish``, walking each component recipe's full
    sub-recipe graph — so an allergen buried in a sub-recipe is caught (``design.md``: *"an
    exclusion that only checks top-level ingredients is not an allergy filter"*).

    Reads only the prefetched graph in ``recipe_graph``; the cycle guard and ``MAX_DEPTH`` cap
    mirror ``recipes.services.flatten`` so a malformed graph cannot loop here either.
    """
    ids: set[int] = set()
    for component in dish.components.all():
        recipe = recipe_graph.get(component.recipe_id)
        if recipe is not None:
            _collect_recipe_ingredient_ids(recipe, ids, seen=frozenset(), depth=0)
    return ids


def _collect_recipe_ingredient_ids(
    recipe: Recipe, ids: set[int], *, seen: frozenset[int], depth: int
) -> None:
    if recipe.pk in seen or depth > MAX_DEPTH:
        return
    seen = seen | {recipe.pk}
    for component in recipe.components.all():
        if component.ingredient_id:
            ids.add(component.ingredient_id)
        elif component.sub_recipe_id:
            _collect_recipe_ingredient_ids(component.sub_recipe, ids, seen=seen, depth=depth + 1)


__all__ = ["build_candidate_pool", "explain_empty_pool"]
