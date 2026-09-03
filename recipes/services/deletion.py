"""Turn a ``PROTECT``-blocked recipe delete into a 409 that names the **parent recipes**
(design.md, "Edge cases": "Deleting a recipe used as a sub-recipe: 409 naming the parents").

Shared by the REST viewset (``recipes.api``) and the HTML delete view (``recipes.views``) so
the rule — and the carve-out that a parent the requester cannot see is *counted, never named*
— lives in one place (CLAUDE.md §6).
"""

from __future__ import annotations

from django.db.models import ProtectedError

from core.exceptions import Conflict, conflict_from_protected_error, describe_blocking_objects
from recipes.models import Recipe, RecipeComponent


def conflict_for_protected_recipe(exc: ProtectedError, *, viewer) -> Conflict:
    """The 409 for ``exc`` raised while deleting a recipe. If every blocker is a
    ``RecipeComponent`` (the recipe is someone's sub-recipe) the message names the parent
    recipes; any other ``PROTECT``ed relation falls back to the generic handler.
    """
    blockers = list(exc.protected_objects)
    components = [obj for obj in blockers if isinstance(obj, RecipeComponent)]
    if len(components) != len(blockers):
        return conflict_from_protected_error(exc)
    return Conflict(_subrecipe_conflict_detail(components, viewer=viewer))


def _subrecipe_conflict_detail(components: list[RecipeComponent], *, viewer) -> str:
    """One ``visible_to`` query covers every parent; ``component.recipe`` is never dereferenced
    (that would be a query per join row), and a parent ``viewer`` cannot see is counted only —
    the body must not leak another user's recipe name (task 05 review).
    """
    parent_ids = {component.recipe_id for component in components}
    visible = list(Recipe.objects.visible_to(viewer).filter(pk__in=parent_ids))
    hidden = len(parent_ids) - len(visible)

    parts: list[str] = []
    if visible:
        parts.append(describe_blocking_objects(visible))
    if hidden:
        parts.append(f"{hidden} other recipe{'' if hidden == 1 else 's'}")
    used_in = " and ".join(parts) if parts else "other recipes"
    return (
        f"Cannot delete this recipe — it is used as a sub-recipe in: {used_in}. "
        "Remove it from those recipes first."
    )
