"""Copy service — deep, atomic, always-private snapshots (design.md, "Copy service").

A copy never carries a pointer into someone else's data: every concrete field is duplicated
onto a brand-new row, ownership and visibility are reset unconditionally, and every declared
child is copied too via ``OwnedModel.copy_children`` rather than merely re-referenced
(MILESTONES.md, C6 — "a copy that the original owner can delete out from under you is not a
copy").

The cycle guard, depth cap, and memoization all live *inside* the recursion itself (``Copier``
below), not in a separate pre-flight walk. An earlier version ran a pre-flight over
``walk_dependencies(obj)`` — which defaults to ``share_dependencies()`` edges — before recursing
over the model-specific ``copy_children()`` edges instead. Those are deliberately different
edge sets (core/services/graph.py's own docstring), so the pre-flight was validating a graph the
copy never actually walks: a model whose ``copy_children`` reaches nodes its
``share_dependencies`` does not got zero cycle/depth protection. Making the guard intrinsic to
the real recursion closes that gap and, as a side effect, gives every copy memoization for
free: a node reachable by two different paths (a diamond in the graph) is copied exactly once,
not once per path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.http import Http404

from core.models import Visibility
from core.services.graph import (
    MAX_DEPTH,
    MAX_NODES,
    CycleError,
    DepthExceededError,
    TooManyNodesError,
)

if TYPE_CHECKING:
    from core.models import OwnedModel

_OVERRIDDEN_FIELDS = {"owner", "visibility", "is_system", "copied_from"}

_NodeKey = tuple[type, object]


class CopyError(Exception):
    """A copy was refused because it would otherwise produce a hollow result: a child of an
    object the copier can see is not itself visible to them (design.md, "Edge cases": "copy
    what is visible and fail loudly on the rest").

    Deliberately distinct from ``Http404``: the *root* object being invisible is
    enumeration-sensitive and stays a 404 (design.md, "Security notes" — copying something you
    cannot see must read as "does not exist"), but a child discovered mid-copy of a parent the
    caller already knows exists is not a guess about something that might not exist. It is a
    specific, nameable failure, and deserves a message that says so rather than a bare 404 on
    an object the caller is looking straight at.
    """


def _clone_field_values(obj: OwnedModel) -> dict[str, object]:
    """Every concrete field value on ``obj`` except its primary key, the four fields
    ``copy_object`` always overrides itself, and the two timestamps Django regenerates on save.

    Read via ``field.attname`` rather than ``field.name`` so a foreign key copies as its raw
    ``_id`` value without fetching the related row — correct for any field type a concrete
    ``OwnedModel`` subclass declares, not just the plain ``CharField`` this task's dummy
    fixtures happen to have.
    """
    values: dict[str, object] = {}
    for concrete_field in obj._meta.concrete_fields:
        if concrete_field.primary_key or concrete_field.name in _OVERRIDDEN_FIELDS:
            continue
        if getattr(concrete_field, "auto_now", False) or getattr(
            concrete_field, "auto_now_add", False
        ):
            continue
        values[concrete_field.attname] = getattr(obj, concrete_field.attname)
    return values


def _node_key(obj: OwnedModel) -> _NodeKey:
    return (obj._meta.concrete_model, obj.pk)


def _new_instance(obj: OwnedModel, *, actor: AbstractBaseUser) -> OwnedModel:
    model = type(obj)
    new_obj = model(
        owner=actor,
        visibility=Visibility.PRIVATE,
        is_system=False,
        copied_from=obj,
        **_clone_field_values(obj),
    )
    new_obj.save()
    return new_obj


class Copier:
    """Passed to ``OwnedModel.copy_children`` so a model's hand-written recursive copy gets the
    cycle guard, the depth cap, and memoization for free, instead of each model having to
    reimplement (or, as happened before this fix, quietly skip) them.

    ``copy(dependency)`` is the only thing a ``copy_children`` override should ever call to
    obtain the copy of one of its own children.
    """

    def __init__(
        self,
        *,
        actor: AbstractBaseUser,
        memo: dict[_NodeKey, OwnedModel],
        path: frozenset[_NodeKey],
        depth: int,
        max_depth: int,
        max_nodes: int,
    ) -> None:
        self._actor = actor
        self._memo = memo
        self._path = path
        self._depth = depth
        self._max_depth = max_depth
        self._max_nodes = max_nodes

    @property
    def actor(self) -> AbstractBaseUser:
        """The user the copies are being made for. A ``copy_children`` override needs this to
        decide whether the actor already owns a reusable copy of one of its children (see
        ``recipes.models._copy_or_reference``)."""
        return self._actor

    def copy(self, dependency: OwnedModel) -> OwnedModel:
        """Return the copy of ``dependency``, creating it (and recursively, its own children)
        the first time it is seen in this operation. A later reference to the same dependency
        — reached by a different path through the graph — returns the exact same copy instead
        of creating a second one, which is what keeps a diamond a diamond instead of a tree.
        """
        key = _node_key(dependency)

        # Checked before the memo lookup: an object still on the current path is an ancestor
        # currently being copied, not a finished sibling-reachable node, even though it is
        # already sitting in ``memo`` (a node is memoized *before* its own children are copied,
        # so it can be found by its own descendants). Checking the memo first would let a real
        # cycle silently "succeed" by handing back a copy that is not finished yet.
        if key in self._path:
            raise CycleError(
                f"Copy dependency cycle detected: an ancestor of {dependency!r} depends on it "
                "transitively."
            )
        if key in self._memo:
            return self._memo[key]
        if self._depth >= self._max_depth:
            raise DepthExceededError(
                f"Copy dependency graph is nested deeper than {self._max_depth} levels "
                f"(hit at {dependency!r})."
            )
        if len(self._memo) >= self._max_nodes:
            raise TooManyNodesError(
                f"Copy dependency graph exceeds {self._max_nodes} distinct nodes."
            )

        manager = type(dependency)._default_manager
        if not manager.visible_to(self._actor).filter(pk=dependency.pk).exists():
            raise CopyError(
                f"Cannot finish this copy: it contains {dependency!s}, which is not visible to you."
            )

        return _copy_recursive(
            dependency,
            actor=self._actor,
            memo=self._memo,
            path=self._path | {key},
            depth=self._depth + 1,
            max_depth=self._max_depth,
            max_nodes=self._max_nodes,
        )


def _copy_recursive(
    obj: OwnedModel,
    *,
    actor: AbstractBaseUser,
    memo: dict[_NodeKey, OwnedModel],
    path: frozenset[_NodeKey],
    depth: int,
    max_depth: int,
    max_nodes: int,
) -> OwnedModel:
    new_obj = _new_instance(obj, actor=actor)
    memo[_node_key(obj)] = new_obj

    copier = Copier(
        actor=actor,
        memo=memo,
        path=path,
        depth=depth,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    obj.copy_children(new_obj, copier=copier)
    return new_obj


def copy_object(obj: OwnedModel, *, actor: AbstractBaseUser, deep: bool = True) -> OwnedModel:
    """Create an independent, private snapshot of ``obj`` owned by ``actor``.

    ``obj`` must be ``.visible_to(actor)`` — copying something invisible raises ``Http404``,
    never a permission error, the same enumeration-safe posture as every other read path
    (design.md, "Security notes": a private object must 404, not 403).

    The new object is always ``PRIVATE`` and never ``is_system``, whatever ``obj`` was
    (inheriting a public visibility would silently republish someone else's work under the
    copier's name), with ``copied_from`` recording provenance and ``shared_with`` starting
    empty. When ``deep`` is true, ``obj.copy_children(new_obj, copier=...)`` performs the
    model-specific recursive copy, guarded against cycles and excessive depth/fan-out by the
    ``Copier`` passed in — the same cycle guard and depth cap the sharing cascade uses, applied
    directly to the graph being copied rather than to a stand-in. If a child reached along the
    way is not visible to ``actor`` (design.md, "Edge cases": a visible parent whose own child
    is not), the whole copy is refused with ``CopyError`` naming the blocking object, rather
    than the child's own 404 surfacing as "the object you asked for does not exist" — the
    parent the caller is looking at very much does exist. The whole operation is one
    transaction: a failed child copy or a mid-operation refusal leaves no partial objects
    behind.
    """
    manager = type(obj)._default_manager
    if not manager.visible_to(actor).filter(pk=obj.pk).exists():
        raise Http404(f"{obj!r} is not visible to {actor!r}.")

    with transaction.atomic():
        if deep:
            root_key = _node_key(obj)
            new_obj = _copy_recursive(
                obj,
                actor=actor,
                memo={},
                path=frozenset({root_key}),
                depth=0,
                max_depth=MAX_DEPTH,
                max_nodes=MAX_NODES,
            )
        else:
            new_obj = _new_instance(obj, actor=actor)

    return new_obj
