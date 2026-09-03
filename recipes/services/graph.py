"""The recipe DAG guard (MILESTONES.md C2; design.md, "The cycle guard").

A recipe graph is a directed *acyclic* graph. Nothing in the data model stops it becoming
cyclic (A contains B contains A), and a cycle makes ``flatten`` recurse until the stack dies.

``assert_no_cycle`` must run on **every** write path that adds or changes a ``sub_recipe`` — the
serializer, the HTML form, and the admin (design.md; three separate tests). Enforcing it on
only one path is how the bad row eventually gets in.

The traversal here is also what ``recipes.services.flatten`` reuses for its own cycle guard and
depth cap, so the two never disagree on what "too deep" or "a cycle" means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from recipes.models import Recipe

#: A practical ceiling on sub-recipe nesting, counted in edges: a chain of five
#: ``recipe -> sub_recipe`` hops is allowed, a sixth is rejected. Beyond this, flattening is
#: slow and the recipe is almost certainly a mistake (design.md).
MAX_DEPTH = 5


class GraphError(Exception):
    """Base class for every malformed-graph condition, so a write path can map all of them to
    one user-facing refusal instead of enumerating each."""


class CycleError(GraphError):
    """Adding a sub-recipe would make a recipe contain itself, directly or transitively."""

    def __init__(self, chain: list[str]) -> None:
        self.chain = list(chain)
        super().__init__("Recipe cycle detected: " + " → ".join(self.chain))


class DepthExceededError(GraphError):
    """The resulting graph would nest deeper than ``MAX_DEPTH`` sub-recipe levels."""

    def __init__(self, chain: list[str], max_depth: int = MAX_DEPTH) -> None:
        self.chain = list(chain)
        self.max_depth = max_depth
        super().__init__(
            f"Recipe nesting would exceed {max_depth} levels: " + " → ".join(self.chain)
        )


def _sub_components(recipe: Recipe) -> list:
    return [c for c in recipe.components.all() if c.sub_recipe_id]


def _find_chain(start: Recipe, target_pk: object, trail: list[Recipe]) -> list[str] | None:
    """Names of the recipes on a path from ``start`` down to the recipe whose pk is
    ``target_pk``, following ``sub_recipe`` edges, or ``None`` if it is unreachable.
    """
    trail = [*trail, start]
    if start.pk == target_pk:
        return [r.name for r in trail]
    seen = {r.pk for r in trail}
    for component in _sub_components(start):
        sub_recipe = component.sub_recipe
        if sub_recipe.pk in seen:
            continue
        found = _find_chain(sub_recipe, target_pk, trail)
        if found is not None:
            return found
    return None


def recipe_depth(recipe: Recipe, *, _trail: tuple = ()) -> int:
    """The number of ``sub_recipe`` edges on the longest chain *below* ``recipe``. A recipe with
    no sub-recipes has depth 0.

    Raises ``CycleError`` if the graph already contains a cycle (a row that bypassed
    ``assert_no_cycle``) rather than recursing forever.
    """
    if recipe.pk in _trail:
        raise CycleError([*(str(pk) for pk in _trail), str(recipe.pk)])
    deepest = 0
    for component in _sub_components(recipe):
        below = recipe_depth(component.sub_recipe, _trail=(*_trail, recipe.pk))
        deepest = max(deepest, 1 + below)
    return deepest


def _depth_above(recipe: Recipe, *, _trail: tuple = ()) -> int:
    """The number of ``sub_recipe`` edges on the longest chain from any top-level recipe down
    to ``recipe`` (following ``used_in`` upward). A recipe used by nothing has depth 0 above.
    """
    if recipe.pk in _trail:
        raise CycleError([*(str(pk) for pk in _trail), str(recipe.pk)])
    deepest = 0
    for component in recipe.used_in.all():
        above = _depth_above(component.recipe, _trail=(*_trail, recipe.pk))
        deepest = max(deepest, 1 + above)
    return deepest


def assert_no_cycle(recipe: Recipe, candidate_sub_recipe: Recipe) -> None:
    """Refuse to add ``candidate_sub_recipe`` as a sub-recipe of ``recipe`` if doing so would
    create a cycle or push the graph past ``MAX_DEPTH``.

    Raises ``CycleError`` (message naming the offending chain) or ``DepthExceededError``.
    """
    if recipe.pk is not None and recipe.pk == candidate_sub_recipe.pk:
        raise CycleError([recipe.name, candidate_sub_recipe.name])

    chain = _find_chain(candidate_sub_recipe, recipe.pk, [])
    if chain is not None:
        # The new edge is recipe -> candidate; ``chain`` runs candidate -> ... -> recipe, so
        # the closed loop is recipe -> candidate -> ... -> recipe.
        raise CycleError([recipe.name, *chain])

    total_depth = _depth_above(recipe) + 1 + recipe_depth(candidate_sub_recipe)
    if total_depth > MAX_DEPTH:
        raise DepthExceededError([recipe.name, candidate_sub_recipe.name])
