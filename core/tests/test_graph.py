"""Tests for core.services.graph.walk_dependencies (03.4).

Not part of Plan/03-Ownership-And-Sharing/test-plan.md's named files — that file's own
dependency-graph coverage (test_share_cascade_terminates_on_cycle,
test_copy_terminates_on_cycle, test_copy_respects_depth_limit) belongs to the sharing and copy
services (03.5/03.6), deferred to a later run. This file covers 03.4's own "done when" clause
directly: a deliberately cyclic fixture terminates and raises CycleError, plus the depth cap
and the basic transitive-traversal behaviour the later services will rely on.

Also covers the iteration-1 review fixes: the memoization rewrite that keeps a fan-out shape
from being re-walked per-path (blocking finding 1), the ``edges`` parameter that lets a caller
walk a graph other than ``share_dependencies()`` (blocking finding 5), the total-node cap, and
the shared ``GraphError`` base (non-blocking finding 3).
"""

from __future__ import annotations

import itertools

import pytest

from core.services.graph import (
    MAX_DEPTH,
    CycleError,
    DepthExceededError,
    GraphError,
    TooManyNodesError,
    walk_dependencies,
)
from core.tests.models import DummyNode

pytestmark = pytest.mark.django_db


def test_leaf_node_has_no_dependencies(alice):
    leaf = DummyNode.objects.create(owner=alice, name="leaf")

    assert walk_dependencies(leaf) == []


def test_walks_direct_dependencies(alice):
    parent = DummyNode.objects.create(owner=alice, name="parent")
    child = DummyNode.objects.create(owner=alice, name="child")
    parent.depends_on.add(child)

    assert walk_dependencies(parent) == [child]


def test_walks_transitive_dependencies(alice):
    grandparent = DummyNode.objects.create(owner=alice, name="grandparent")
    parent = DummyNode.objects.create(owner=alice, name="parent")
    child = DummyNode.objects.create(owner=alice, name="child")
    grandparent.depends_on.add(parent)
    parent.depends_on.add(child)

    result = walk_dependencies(grandparent)

    assert set(result) == {parent, child}


def test_diamond_dependency_appears_once(alice):
    """Two branches converging on the same leaf must not duplicate it in the result."""
    top = DummyNode.objects.create(owner=alice, name="top")
    left = DummyNode.objects.create(owner=alice, name="left")
    right = DummyNode.objects.create(owner=alice, name="right")
    shared_leaf = DummyNode.objects.create(owner=alice, name="shared_leaf")
    top.depends_on.add(left, right)
    left.depends_on.add(shared_leaf)
    right.depends_on.add(shared_leaf)

    result = walk_dependencies(top)

    assert result.count(shared_leaf) == 1
    assert set(result) == {left, right, shared_leaf}


def test_cycle_terminates_and_raises(alice):
    """A deliberately cyclic fixture (A -> B -> C -> A) must terminate, not hang, and must
    raise CycleError rather than recursing forever.
    """
    a = DummyNode.objects.create(owner=alice, name="a")
    b = DummyNode.objects.create(owner=alice, name="b")
    c = DummyNode.objects.create(owner=alice, name="c")
    a.depends_on.add(b)
    b.depends_on.add(c)
    c.depends_on.add(a)

    with pytest.raises(CycleError):
        walk_dependencies(a)


def test_self_referential_cycle_raises(alice):
    a = DummyNode.objects.create(owner=alice, name="self_loop")
    a.depends_on.add(a)

    with pytest.raises(CycleError):
        walk_dependencies(a)


def test_depth_beyond_cap_raises(alice):
    """A chain deeper than MAX_DEPTH levels must raise rather than recurse indefinitely, even
    with no cycle present.
    """
    nodes = [DummyNode.objects.create(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 3)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)

    with pytest.raises(DepthExceededError):
        walk_dependencies(nodes[0])


def test_chain_exactly_at_cap_succeeds(alice):
    """A chain whose deepest node sits exactly ``MAX_DEPTH`` levels below the root, with no
    grandchildren past it, must not raise — the cap only trips when something tries to recurse
    *past* that depth.
    """
    nodes = [DummyNode.objects.create(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 1)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)

    result = walk_dependencies(nodes[0])

    assert set(result) == set(nodes[1:])


def test_cycle_longer_than_cap_raises_a_graph_error(alice):
    """A cycle longer than ``MAX_DEPTH`` surfaces as ``DepthExceededError``, not ``CycleError``,
    because the depth check trips before the loop can close back on the origin — termination
    still holds either way. ``GraphError`` is the shared base 03.5/03.6 must catch to treat a
    malformed graph as one condition regardless of which specific check tripped.
    """
    nodes = [DummyNode.objects.create(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 2)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)
    nodes[-1].depends_on.add(nodes[0])

    with pytest.raises(GraphError):
        walk_dependencies(nodes[0])


def test_unsaved_object_is_rejected(alice):
    """An unsaved object has no stable primary key to dedup or cycle-check on — rejected
    explicitly rather than silently colliding with every other unsaved instance under a
    ``pk=None`` key.
    """
    unsaved = DummyNode(owner=alice, name="unsaved")

    with pytest.raises(ValueError):
        walk_dependencies(unsaved)


def test_exceeds_node_cap_raises(alice):
    root = DummyNode.objects.create(owner=alice, name="root")
    children = [DummyNode.objects.create(owner=alice, name=f"n{i}") for i in range(5)]
    root.depends_on.set(children)

    with pytest.raises(TooManyNodesError):
        walk_dependencies(root, max_nodes=3)


def test_walks_a_custom_edge_function(alice):
    """The ``edges`` parameter (blocking finding 5) must let a caller walk a graph shape other
    than ``share_dependencies()`` — proven here with an edge function that deliberately ignores
    ``DummyNode.depends_on``/``share_dependencies`` entirely, the way 03.6's copy service will
    need to walk ``copy_children`` edges and task 05's flattener will need to walk
    ``RecipeComponent`` edges.
    """
    a = DummyNode.objects.create(owner=alice, name="a")
    b = DummyNode.objects.create(owner=alice, name="b")
    c = DummyNode.objects.create(owner=alice, name="c")
    graph = {a.pk: [b], b.pk: [c], c.pk: []}

    result = walk_dependencies(a, edges=lambda node: graph[node.pk])

    assert result == [b, c]


def test_layered_fan_out_does_not_explode_query_count(alice, django_assert_max_num_queries):
    """Regression test for blocking finding 1: re-walking every *path* to a node instead of
    memoizing completed nodes made this exponential. Root + ``MAX_DEPTH`` levels of 6 nodes,
    every node at level *i* depending on every node at level *i+1* (no cycle, exactly at the
    depth cap) — the shape measured at 9,331 queries under the old algorithm. The fixed
    algorithm re-walks a node at most ``MAX_DEPTH + 1`` times total, so this must stay a small,
    roughly-linear multiple of the node count, not anywhere near that.

    The bound is tightened to 40 (measured actual cost: 31 queries) rather than left at a loose
    200, per 03-Ownership-And-Sharing review iteration-2 blocking finding 8: a bound that loose
    only catches the original exponential blow-up, not a partial regression to a cheaper but
    still-wrong traversal.
    """
    root = DummyNode.objects.create(owner=alice, name="root")
    levels = [
        [DummyNode.objects.create(owner=alice, name=f"L{level}_{i}") for i in range(6)]
        for level in range(MAX_DEPTH)
    ]

    root.depends_on.set(levels[0])
    for previous_level, next_level in itertools.pairwise(levels):
        for node in previous_level:
            node.depends_on.set(next_level)

    with django_assert_max_num_queries(40):
        result = walk_dependencies(root)

    assert len(result) == 6 * MAX_DEPTH


def test_shared_node_reachable_at_two_depths_is_rechecked_at_the_deeper_one(alice):
    """Regression test for 03-Ownership-And-Sharing review iteration-2 blocking finding 8: the
    ``deepest_validated`` memoization is what keeps ``DepthExceededError`` deterministic rather
    than traversal-order-dependent. Every other depth test in this file uses a straight chain,
    in which no node is ever reachable at two different depths, so none of them can observe the
    difference between the real ``deepest_validated``-aware skip and a naive
    ``if child_key in seen: continue``.

    Here ``x`` is reachable directly from ``root`` (depth 1, discovered first because the edge
    function yields it before the long chain) and again via a four-hop chain through
    ``c0``..``c3`` (depth 5). ``x`` itself has a two-level chain below it (``x1``, ``x2``), so
    the deep reoccurrence puts a real violation two levels past ``MAX_DEPTH``. A shallow-first
    memo that only tracks "seen at all" marks ``x`` fully explored after the depth-1 visit and
    never re-descends into it from the depth-5 arrival, silently missing that violation.
    """
    root = DummyNode.objects.create(owner=alice, name="root")
    x = DummyNode.objects.create(owner=alice, name="x")
    x1 = DummyNode.objects.create(owner=alice, name="x1")
    x2 = DummyNode.objects.create(owner=alice, name="x2")
    c0 = DummyNode.objects.create(owner=alice, name="c0")
    c1 = DummyNode.objects.create(owner=alice, name="c1")
    c2 = DummyNode.objects.create(owner=alice, name="c2")
    c3 = DummyNode.objects.create(owner=alice, name="c3")
    graph = {
        root.pk: [x, c0],  # x discovered shallow (depth 1) before the long chain reaches it
        x.pk: [x1],
        x1.pk: [x2],
        x2.pk: [],
        c0.pk: [c1],
        c1.pk: [c2],
        c2.pk: [c3],
        c3.pk: [x],  # x reoccurs here at depth 5, with two more levels still below it
    }

    with pytest.raises(DepthExceededError):
        walk_dependencies(root, edges=lambda node: graph[node.pk])
