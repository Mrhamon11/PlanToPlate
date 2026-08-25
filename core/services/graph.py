"""Dependency-graph traversal shared by the sharing cascade, the copy service, and — later —
the recipe flattener (design.md, "The cascade"; MILESTONES.md, "Sub-recipes form a DAG").

Every model that can contain others declares its children via ``OwnedModel.share_dependencies``
(default: none). ``walk_dependencies`` follows that graph transitively, refusing to loop forever
on a cycle and refusing to recurse past a sane depth — the same two guarantees the recipe
flattener will need for ``RecipeComponent.sub_recipe`` once task 05 lands.

``walk_dependencies`` applies **no visibility or ownership filter of its own** — it just returns
what the graph says is reachable. 03.5's cascade ("for every dependency owned by the actor") and
03.6's copy service ("copy what is visible and fail loudly on the rest") must each apply
``visible_to``/ownership themselves on top of this walk; nothing here does it for them.

The edge function defaults to ``share_dependencies()`` so today's two callers (sharing, copy —
once they land) need no changes, but it is a parameter precisely so this helper is reusable for
graphs that are *not* the share graph: the copy service walks ``copy_children``-shaped edges
(sharing and copying are declared as separate hooks because they are not always the same set of
children), and the future recipe flattener walks ``RecipeComponent`` edges carrying
quantity/unit data that a plain list of objects cannot represent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import OwnedModel

MAX_DEPTH = 5
MAX_NODES = 1000


class GraphError(Exception):
    """Base class for every error ``walk_dependencies`` can raise, so callers that need to
    treat "the graph is malformed" as one condition (03.5/03.6, both of which must turn this
    into a user-facing refusal rather than a 500) can catch one type instead of enumerating the
    specific ways a graph can be broken.
    """


class CycleError(GraphError):
    """A dependency graph loops back on itself instead of terminating."""


class DepthExceededError(GraphError):
    """A dependency graph is nested deeper than the configured depth cap.

    Note: a cycle longer than the depth cap surfaces as this error rather than ``CycleError``,
    because the depth check trips before the loop can close back on itself. Termination still
    holds either way — catch ``GraphError`` to handle both uniformly.
    """


class TooManyNodesError(GraphError):
    """A dependency graph has more distinct nodes than the configured cap allows.

    Bounds a legitimately shallow-but-enormous graph independently of the depth cap, which only
    bounds how *deep* a single path may run, not how many distinct nodes a shallow graph may
    fan out to.
    """


def _default_edges(node: OwnedModel) -> Iterable[OwnedModel]:
    return node.share_dependencies()


def _node_key(node: OwnedModel) -> tuple[type, object]:
    """A stable identity for dedup/cycle tracking.

    Keyed on ``_meta.concrete_model`` rather than ``type(node)`` so a proxy model instance or an
    instance reached through multi-table inheritance still keys the same as the concrete row it
    actually is — ``type()`` differs for those, ``_meta.concrete_model`` does not. (Deferred
    instances built by ``.only()``/``.defer()`` do *not* need this: Django has not generated a
    runtime subclass for them since 1.10, so ``type(node) is node.__class__`` holds for those
    regardless.)

    An unsaved object has no stable identity to key on at all. This raises ``ValueError`` rather
    than a ``GraphError`` deliberately — it is a programming error in the caller (walking a graph
    that includes an object nobody saved yet), not a property of the graph itself, so it should
    not be catchable by the same "the graph is malformed" handling 03.5/03.6 wrap around
    ``GraphError``.
    """
    if node.pk is None:
        raise ValueError(f"Cannot walk dependencies of an unsaved object: {node!r}")
    return (node._meta.concrete_model, node.pk)


def walk_dependencies(
    obj: OwnedModel,
    *,
    edges: Callable[[OwnedModel], Iterable[OwnedModel]] = _default_edges,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> list[OwnedModel]:
    """Return every object ``obj`` transitively depends on (per ``edges``), each appearing once,
    in the order first encountered.

    Raises ``CycleError`` if a dependency chain loops back onto an object still on the current
    path, ``DepthExceededError`` if the chain runs deeper than ``max_depth`` levels below
    ``obj``, and ``TooManyNodesError`` if the graph contains more than ``max_nodes`` distinct
    objects — all three checked before recursing further, so a malformed graph fails fast
    instead of exhausting the stack or the database.

    A node already fully explored is not re-walked from a path that reaches it at an equal or
    shallower depth than the deepest depth it has already been proven safe from — that repeat
    walk cannot discover anything the first one did not already cover, since more depth budget
    can only make a passing subtree pass more easily. A node reached at a *deeper* position than
    any depth it has been proven safe from **is** re-walked, since the shallower proof does not
    show the cap still holds with less budget remaining. That bounds any single node to at most
    ``max_depth + 1`` re-walks (once per depth level it can newly appear at) rather than once per
    path reaching it, which is what makes a fan-out shape exponential.

    This memoization requires ``edges`` to be a pure function of its argument: calling
    ``edges(n)`` twice must return the same set of children every time within one
    ``walk_dependencies`` call. An edge function that consults mutable state, or re-queries a
    relation the caller is concurrently mutating, can silently defeat the skip above.
    """
    seen: set[tuple[type, object]] = set()
    deepest_validated: dict[tuple[type, object], int] = {}
    ordered: list[OwnedModel] = []
    root_key = _node_key(obj)

    def _walk(node: OwnedModel, path: frozenset[tuple[type, object]], depth: int) -> None:
        for child in edges(node):
            child_key = _node_key(child)
            if child_key in path:
                raise CycleError(
                    f"Dependency cycle detected: {node!r} depends on {child!r}, which "
                    "already depends on it transitively."
                )
            if depth >= max_depth:
                raise DepthExceededError(
                    f"Dependency graph below {obj!r} is deeper than {max_depth} levels "
                    f"(hit at {child!r})."
                )

            child_depth = depth + 1
            if child_key in seen:
                if child_depth <= deepest_validated[child_key]:
                    continue
            else:
                seen.add(child_key)
                ordered.append(child)
                if len(seen) > max_nodes:
                    raise TooManyNodesError(
                        f"Dependency graph below {obj!r} exceeds {max_nodes} distinct nodes."
                    )

            deepest_validated[child_key] = child_depth
            _walk(child, path | {child_key}, child_depth)

    _walk(obj, frozenset({root_key}), depth=0)
    return ordered
