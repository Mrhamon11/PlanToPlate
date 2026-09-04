"""Dish-level derived values (``Plan/06-Dishes-And-RecipeBooks/design.md``, "Derived
properties"). All three are thin wrappers over task 05: a dish adds nothing to the flatten
algorithm, it just scales each component recipe by its ``servings`` and aggregates the lot.

Every quantity is ``Decimal``; ``float`` never appears.

**Visibility.** ``design.md`` "Security notes": *"Book and dish detail serializers expand
recipes through ``visible_to``, never raw."* A shared dish can still contain a recipe a given
reader can no longer see — unsharing a child does not cascade back from its parent (D31) — so
the detail serializer and ``flatten`` both drop those components. ``viewer=None`` is the
trusted internal caller (e.g. the planner walking its owner's own dishes) and skips the
filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from recipes.models import Recipe
from recipes.services.flatten import FlatLine, aggregate
from recipes.services.flatten import flatten as flatten_recipe

if TYPE_CHECKING:
    from meals.models import Dish, DishComponent

_TYPEAHEAD_LIMIT = 20


def recipe_choices(
    user: object, query: str | None, *, limit: int = _TYPEAHEAD_LIMIT
) -> list[Recipe]:
    """Recipes ``visible_to(user)`` whose name matches ``query`` — the dish/book typeahead
    never surfaces an invisible recipe's name (``design.md``, "Security notes").
    """
    queryset = Recipe.objects.visible_to(user).select_related("yield_unit").order_by("name")
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    return list(queryset[:limit])


def total_minutes_for(recipes: list[Recipe]) -> int:
    """The longest single prep plus the sum of every cook time — closer to reality than a
    naive total, since a cook works on things in parallel (``design.md``). Approximate, and
    labelled as such in the UI. An empty list is ``0``, not an error.
    """
    if not recipes:
        return 0
    max_prep = max(recipe.prep_minutes for recipe in recipes)
    total_cook = sum(recipe.cook_minutes for recipe in recipes)
    return max_prep + total_cook


def roles_for(recipes: list[Recipe]) -> set[str]:
    """The set of recipe roles — the planner checks this against a ``BALANCED`` template
    (``design.md``).
    """
    return {recipe.role for recipe in recipes}


def total_minutes(dish: Dish) -> int:
    return total_minutes_for([component.recipe for component in dish.components.all()])


def roles(dish: Dish) -> set[str]:
    return roles_for([component.recipe for component in dish.components.all()])


def visible_components(dish: Dish, viewer: object | None) -> list[DishComponent]:
    """``dish``'s components whose recipe is ``visible_to(viewer)``, in position order.

    ``viewer=None`` skips the filter for trusted internal callers. Any real request must pass
    its user so a component recipe that is no longer visible to that reader (D31) is dropped
    rather than leaked through the dish.
    """
    components = list(dish.components.all())
    if viewer is None:
        return components
    visible_ids = set(
        Recipe.objects.visible_to(viewer)
        .filter(pk__in={component.recipe_id for component in components})
        .values_list("pk", flat=True)
    )
    return [component for component in components if component.recipe_id in visible_ids]


@dataclass(frozen=True)
class DishComponentDraft:
    recipe: Recipe
    servings: Decimal


def parse_dish_component_drafts(post: object, *, user: object) -> list[DishComponentDraft]:
    """Build the component drafts for a dish form submission from its parallel POST arrays
    (``component_recipe`` / ``component_servings``).

    An empty submission is allowed — ``design.md`` "Edge cases": *"An empty dish: allowed to
    exist while being built"* — and yields an empty draft list. A row that carries a
    ``component_servings`` value but no recipe is still rejected, as is a recipe the requester
    cannot see (the flagship IDOR defence — ``design.md``, "Security notes") or a non-positive
    ``servings``. Row order becomes ``position``.
    """
    refs = post.getlist("component_recipe")
    servings_values = post.getlist("component_servings")

    rows: list[tuple[str, str]] = []
    for i, ref in enumerate(refs):
        ref = ref.strip()
        raw_servings = (servings_values[i] if i < len(servings_values) else "").strip()
        if not ref and not raw_servings:
            continue
        if not ref:
            raise ValidationError("Every dish row must reference a recipe.")
        rows.append((ref, raw_servings))
    if not rows:
        return []

    recipe_ids = {int(ref) for ref, _ in rows if ref.isdigit()}
    if len(recipe_ids) != len(rows):
        raise ValidationError("Every dish row must reference a recipe.")

    visible = {
        recipe.pk: recipe for recipe in Recipe.objects.visible_to(user).filter(pk__in=recipe_ids)
    }
    if len(visible) != len(recipe_ids):
        raise ValidationError("One of the rows references a recipe that is not available to you.")

    drafts: list[DishComponentDraft] = []
    for ref, raw_servings in rows:
        try:
            servings = Decimal(raw_servings) if raw_servings else Decimal(1)
        except (InvalidOperation, TypeError):
            raise ValidationError("Servings must be a number.") from None
        if not servings.is_finite() or servings <= 0:
            raise ValidationError("Servings must be greater than zero.")
        drafts.append(DishComponentDraft(recipe=visible[int(ref)], servings=servings))
    return drafts


def replace_dish_components(dish: Dish, drafts: list[DishComponentDraft]) -> None:
    """Replace ``dish``'s component set with ``drafts``, positioned in list order. Callers wrap
    this in the same transaction as the ``Dish`` row write.
    """
    from meals.models import DishComponent

    dish.components.all().delete()
    for position, draft in enumerate(drafts):
        DishComponent.objects.create(
            dish=dish,
            recipe=draft.recipe,
            servings=draft.servings,
            position=position,
        )


def flatten_dish(
    dish: Dish, *, exclude_staples: bool = False, viewer: object | None = None
) -> list[FlatLine]:
    """Expand every component recipe (scaled by its ``servings``), then aggregate across the
    whole dish so a shared ingredient becomes one line (``design.md``: "the shopping list's
    entry point").

    Task 05's sub-recipe yield scaling still applies underneath — ``flatten_recipe`` handles
    it — so a component's ``servings`` multiplies on top of whatever the sub-recipe graph
    already resolves to. A component whose recipe is not visible to ``viewer`` is skipped
    entirely, graph and all.
    """
    lines: list[FlatLine] = []
    for component in visible_components(dish, viewer):
        lines.extend(
            flatten_recipe(
                component.recipe,
                factor=component.servings,
                exclude_staples=exclude_staples,
            )
        )
    return aggregate(lines)
