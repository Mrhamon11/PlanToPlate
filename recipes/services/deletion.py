"""Turn a ``PROTECT``-blocked recipe delete into a 409 that names what still depends on the
recipe (``Plan/05-Recipes/design.md``, "Edge cases"; ``Plan/06-Dishes-And-RecipeBooks/
design.md``, "Edge cases": "Deleting a recipe used in a dish: ``PROTECT`` → 409 naming the
dishes").

Shared by the REST viewset (``recipes.api``) and the HTML delete view (``recipes.views``) so
the rule — and the carve-out that a parent the requester cannot see is *counted, never named*
— lives in one place (CLAUDE.md §6).
"""

from __future__ import annotations

from django.apps import apps
from django.db.models import Model, ProtectedError

from core.exceptions import Conflict, conflict_from_protected_error, describe_blocking_objects
from recipes.models import Recipe, RecipeComponent


def conflict_for_protected_recipe(exc: ProtectedError, *, viewer) -> Conflict:
    """The 409 for ``exc`` raised while deleting a recipe.

    ``RecipeComponent`` blockers mean the recipe is someone's sub-recipe; ``DishComponent``
    blockers mean it is part of a dish. The message names the parents the ``viewer`` can see
    and counts the rest. Any other ``PROTECT``ed relation falls back to the generic handler.
    """
    dish_component = apps.get_model("meals", "DishComponent")
    dish_model = apps.get_model("meals", "Dish")

    blockers = list(exc.protected_objects)
    sub_recipe_blockers = [obj for obj in blockers if isinstance(obj, RecipeComponent)]
    dish_blockers = [obj for obj in blockers if isinstance(obj, dish_component)]
    if len(sub_recipe_blockers) + len(dish_blockers) != len(blockers):
        return conflict_from_protected_error(exc)

    clauses: list[str] = []
    if sub_recipe_blockers:
        parents = _describe_parents(
            {obj.recipe_id for obj in sub_recipe_blockers},
            model=Recipe,
            viewer=viewer,
            noun="recipe",
        )
        clauses.append(f"used as a sub-recipe in: {parents}")
    if dish_blockers:
        dish_ids = {obj.dish_id for obj in dish_blockers}
        parents = _describe_parents(
            dish_ids,
            model=dish_model,
            viewer=viewer,
            noun="dish",
            plural="dishes",
        )
        label = "dish" if len(dish_ids) == 1 else "dishes"
        clauses.append(f"part of the {label}: {parents}")

    detail = (
        f"Cannot delete this recipe — it is {'; and it is '.join(clauses)}. "
        "Remove those references first."
    )
    return Conflict(detail)


def _describe_parents(
    parent_ids: set[object],
    *,
    model: type[Model],
    viewer,
    noun: str,
    plural: str | None = None,
) -> str:
    """Name the parents ``viewer`` can see, count the ones they cannot. One ``visible_to``
    query covers them all; a parent the viewer cannot see is counted only — the body must not
    leak another user's name (task 05 review).
    """
    plural = plural or f"{noun}s"
    visible = list(model.objects.visible_to(viewer).filter(pk__in=parent_ids))
    hidden = len(parent_ids) - len(visible)

    parts: list[str] = []
    if visible:
        parts.append(describe_blocking_objects(visible))
    if hidden:
        parts.append(f"{hidden} other {noun if hidden == 1 else plural}")
    return " and ".join(parts) if parts else f"other {plural}"
