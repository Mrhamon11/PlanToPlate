"""Compose a transient dish from separate recipes when no existing ``Dish`` fits a ``BALANCED``
slot (``Plan/08-Meal-Planner/design.md``, "Composing a dish from recipes").

The requirement is literal: *"randomly select recipes to construct a dish (protein + carb +
vegetable)"*. This module builds the three role pools once — ``visible_to`` the requester,
minus the profile's hard exclusions (excluded tags, and excluded ingredients checked through
the flattened sub-recipe graph, exactly as the dish candidate pool does) — and the generator
picks one recipe from each with its seeded RNG.

The result is an **unsaved** ``Dish`` carrying its chosen recipes on ``_composed_recipes``.
``planner.services.persist`` turns it into real ``Dish`` / ``DishComponent`` rows only if the
user keeps the plan, so regenerating five times litters nothing (test-plan: *"experimentation
litters the database"*).

``tag_limits`` **is** honoured: the composer takes the slot's remaining tag budget, skips any
recipe whose own tags would push a limited tag over budget, and the generator decrements that
budget for the composed dish's combined recipe tags exactly as it does for a real dish. When
the budget leaves no viable recipe for a role the slot degrades to an explained unfilled entry
(``design.md``, "Composing a dish from recipes": *"respecting the same exclusions and
limits"*).

**Distinctness.** A plan never repeats a dish (``test-plan.md``), and ``save_plan`` collapses
two entries that composed the identical recipe trio onto **one** ``Dish`` row — so composing
the same trio twice would silently repeat a dinner. The composer prefers recipes not yet used
by an earlier composed dish this week (``avoid_recipe_ids``) and refuses to return a trio whose
signature is in ``forbidden_signatures`` (returning ``None`` → the slot degrades to an
explained unfilled entry). With a small library that means the first BALANCED slot composes a
trio and the surplus slots go honestly unfilled rather than repeating it.

**Not applied to a composed dish:** ``favorites_bias`` — it keys on ``DishStats`` and a
recipe has none. ``max_total_minutes`` *is* enforced, against the trio's combined time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from meals.models import Dish
from meals.services.dishes import total_minutes_for
from planner.services.candidates import collect_recipe_ingredient_ids
from recipes.models import Recipe, RecipeRole

if TYPE_CHECKING:
    import random

    from planner.models import MealPlanProfile

#: Protein, then carb, then vegetable — the order the design names, and the order the composed
#: dish's name reads in.
COMPOSED_ROLES: tuple[str, ...] = (
    RecipeRole.PROTEIN.value,
    RecipeRole.CARB.value,
    RecipeRole.VEGETABLE.value,
)


def build_recipe_role_pools(user: object, profile: MealPlanProfile) -> dict[str, list[Recipe]]:
    """One ``{role: [Recipe, ...]}`` map for the three composable roles, each list ordered by
    ``pk`` for a reproducible pick.

    Every recipe is ``visible_to(user)`` — a composed dish must never surface a recipe the
    requester cannot see, the same data-leak rule as the dish pool. Recipes carrying an
    excluded tag, or (through their whole sub-recipe graph) an excluded ingredient, are
    dropped.
    """
    excluded_tag_ids = set(profile.excluded_tags.values_list("pk", flat=True))
    excluded_ingredient_ids = set(profile.excluded_ingredients.values_list("pk", flat=True))

    pools: dict[str, list[Recipe]] = {}
    for role in COMPOSED_ROLES:
        queryset = Recipe.objects.visible_to(user).filter(role=role)
        if excluded_tag_ids:
            queryset = queryset.exclude(tags__in=excluded_tag_ids)
        queryset = (
            queryset.with_component_graph().prefetch_related("tags").order_by("pk").distinct()
        )

        recipes: list[Recipe] = []
        for recipe in queryset:
            if excluded_ingredient_ids:
                ingredient_ids: set[int] = set()
                collect_recipe_ingredient_ids(recipe, ingredient_ids, seen=frozenset(), depth=0)
                if ingredient_ids & excluded_ingredient_ids:
                    continue
            recipes.append(recipe)
        pools[role] = recipes
    return pools


def compose_balanced_dish(
    role_pools: dict[str, list[Recipe]],
    rng: random.Random,
    *,
    avoid_recipe_ids: frozenset[int] | set[int] = frozenset(),
    forbidden_signatures: frozenset[frozenset[int]] | set[frozenset[int]] = frozenset(),
    max_total_minutes: int | None = None,
    tag_budget: dict[str, int] | None = None,
) -> Dish | None:
    """Pick one recipe per role and return an unsaved ``Dish`` composed of the three.

    Returns ``None`` — the slot then degrades to an explained unfilled entry — when any role
    has no candidate recipe, when every candidate for a role would push a ``tag_budget`` tag
    over its limit, when the trio's combined time exceeds ``max_total_minutes``, or when the
    chosen trio's signature is in ``forbidden_signatures`` (an identical trio already composed
    for this plan — repeating it would repeat a dinner).

    ``avoid_recipe_ids`` are preferred against (recipes already used by an earlier composed
    dish this week) but not forbidden: a role with only used recipes still yields one rather
    than leaving the slot empty.

    ``forbidden_signatures`` is a set of ``frozenset`` recipe-id trios already composed for
    this plan. The RNG is still consumed when a forbidden trio is drawn and rejected, so the
    outcome stays deterministic under a fixed seed.

    ``tag_budget`` is the slot's remaining ``profile.tag_limits`` allowance ({lowercased tag:
    count left}). A recipe carrying a tag already at or below zero is skipped, and each pick
    spends the budget so the second and third recipes cannot re-breach a tag the first one
    exhausted.
    """
    chosen: list[Recipe] = []
    used: set[int] = set(avoid_recipe_ids)
    budget = dict(tag_budget) if tag_budget else None
    for role in COMPOSED_ROLES:
        pool = role_pools.get(role) or []
        if not pool:
            return None
        viable = [
            recipe for recipe in pool if budget is None or _recipe_within_budget(recipe, budget)
        ]
        if not viable:
            return None
        fresh = [recipe for recipe in viable if recipe.pk not in used]
        pick = rng.choice(fresh or viable)
        chosen.append(pick)
        used.add(pick.pk)
        if budget is not None:
            for tag in _recipe_tag_names(pick):
                if tag in budget:
                    budget[tag] -= 1

    if max_total_minutes is not None and total_minutes_for(chosen) > max_total_minutes:
        return None

    if frozenset(recipe.pk for recipe in chosen) in forbidden_signatures:
        return None

    return _transient_dish(chosen)


def composed_dish_name(recipes: list[Recipe]) -> str:
    """ "Roast Chicken + Jasmine Rice + Green Beans" — the design's naming (``design.md``)."""
    return " + ".join(recipe.name for recipe in recipes)


def _recipe_tag_names(recipe: Recipe) -> set[str]:
    return {tag.name.lower() for tag in recipe.tags.all()}


def _recipe_within_budget(recipe: Recipe, budget: dict[str, int]) -> bool:
    return not any(budget.get(tag, 1) <= 0 for tag in _recipe_tag_names(recipe))


def _transient_dish(recipes: list[Recipe]) -> Dish:
    dish = Dish(name=composed_dish_name(recipes))
    dish._composed_recipes = list(recipes)
    dish._composed_tags = {tag for recipe in recipes for tag in _recipe_tag_names(recipe)}
    dish._is_composed = True
    return dish


def is_composed(dish: Dish) -> bool:
    """True for a dish ``compose_balanced_dish`` built and nobody has persisted yet."""
    return getattr(dish, "_is_composed", False) and dish.pk is None


__all__ = [
    "COMPOSED_ROLES",
    "build_recipe_role_pools",
    "compose_balanced_dish",
    "composed_dish_name",
    "is_composed",
]
