"""Plan/03-Ownership-And-Sharing/test-plan.md, "Copy service — core/tests/test_copying.py".

``test_copy_does_not_carry_user_stats`` is deliberately absent: no per-user stats model
(``RecipeStats``/``DishStats``) exists yet (task 05+), so there is nothing to assert beyond "the
copy service does not invent one," which ``test_copy_creates_independent_object`` and
``test_deep_copy_copies_children`` already cover by construction.
"""

from __future__ import annotations

import itertools

import pytest
from django.http import Http404

from core.models import Visibility
from core.services.copying import CopyError, copy_object
from core.services.graph import MAX_DEPTH, CycleError, DepthExceededError
from core.tests.models import DummyDivergentNode, DummyNode, DummyOwned

pytestmark = pytest.mark.django_db


def test_copy_creates_independent_object(alice, bob, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.PUBLIC, name="original")

    copy = copy_object(original, actor=bob)

    assert copy.pk != original.pk
    assert copy.owner == bob


def test_copy_is_always_private(alice, bob, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    copy = copy_object(original, actor=bob)

    assert copy.visibility == Visibility.PRIVATE


def test_copy_sets_copied_from(alice, bob, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    copy = copy_object(original, actor=bob)

    assert copy.copied_from_id == original.pk


def test_copy_does_not_carry_shares(alice, bob, carol, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.SHARED)
    original.shared_with.add(bob)

    copy = copy_object(original, actor=bob)

    assert copy.shared_with.count() == 0


def test_cannot_copy_invisible_object(alice, carol, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    with pytest.raises(Http404):
        copy_object(original, actor=carol)


def test_can_copy_shared_object(alice, bob, make_dummy):
    original = make_dummy(owner=alice, visibility=Visibility.SHARED)
    original.shared_with.add(bob)

    copy = copy_object(original, actor=bob)

    assert copy.owner == bob


def test_can_copy_system_object(admin, make_dummy):
    original = make_dummy(owner=None, is_system=True)

    copy = copy_object(original, actor=admin)

    assert copy.is_system is False
    assert copy.owner == admin
    assert DummyOwned.objects.editable_by(admin).filter(pk=copy.pk).exists()


def test_deep_copy_copies_children(alice, make_dummy_node):
    parent = make_dummy_node(owner=alice, name="parent")
    child = make_dummy_node(owner=alice, name="child")
    parent.depends_on.add(child)

    copy = copy_object(parent, actor=alice)

    assert copy.depends_on.count() == 1
    copied_child = copy.depends_on.get()
    assert copied_child.pk != child.pk
    assert copied_child.owner == alice
    assert copied_child.copied_from_id == child.pk


def test_editing_original_does_not_affect_copy(alice, make_dummy):
    original = make_dummy(owner=alice, name="original")
    copy = copy_object(original, actor=alice)

    original.name = "changed original"
    original.save()
    copy.refresh_from_db()
    assert copy.name == "original"

    copy.name = "changed copy"
    copy.save()
    original.refresh_from_db()
    assert original.name == "changed original"


def test_deleting_original_does_not_affect_copy(alice, make_dummy):
    original = make_dummy(owner=alice)
    copy = copy_object(original, actor=alice)

    original.delete()

    copy.refresh_from_db()
    assert copy.copied_from_id is None


def test_copy_is_atomic(alice, make_dummy_node, monkeypatch):
    """With a child save patched to fail partway through, no partial objects remain."""
    parent = make_dummy_node(owner=alice, name="parent")
    child_a = make_dummy_node(owner=alice, name="child_a")
    child_b = make_dummy_node(owner=alice, name="child_b")
    parent.depends_on.add(child_a, child_b)

    original_save = DummyNode.save
    calls = {"count": 0}

    def flaky_save(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated failure mid-copy")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(DummyNode, "save", flaky_save, raising=True)

    with pytest.raises(RuntimeError):
        copy_object(parent, actor=alice)

    assert DummyNode.objects.filter(copied_from__isnull=False).count() == 0


def test_copy_respects_depth_limit(alice, make_dummy_node):
    nodes = [make_dummy_node(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 3)]
    for parent, child in itertools.pairwise(nodes):
        parent.depends_on.add(child)

    with pytest.raises(DepthExceededError):
        copy_object(nodes[0], actor=alice)

    assert DummyNode.objects.filter(copied_from__isnull=False).count() == 0


def test_copy_terminates_on_cycle(alice, make_dummy_node):
    a = make_dummy_node(owner=alice, name="a")
    b = make_dummy_node(owner=alice, name="b")
    a.depends_on.add(b)
    b.depends_on.add(a)

    with pytest.raises(CycleError):
        copy_object(a, actor=alice)

    assert DummyNode.objects.filter(copied_from__isnull=False).count() == 0


def test_deep_copy_deduplicates_diamond_dependency(alice, make_dummy_node):
    """Review finding (security #2): a shared child reached by two different paths must be
    copied exactly once, and both copied parents must point at the *same* copy — a diamond
    must stay a diamond, not become a tree with the leaf duplicated per path.
    """
    root = make_dummy_node(owner=alice, name="root")
    left = make_dummy_node(owner=alice, name="left")
    right = make_dummy_node(owner=alice, name="right")
    shared_leaf = make_dummy_node(owner=alice, name="shared_leaf")
    root.depends_on.add(left, right)
    left.depends_on.add(shared_leaf)
    right.depends_on.add(shared_leaf)

    copy = copy_object(root, actor=alice)

    assert DummyNode.objects.filter(copied_from__isnull=False).count() == 4
    children_by_name = {child.name: child for child in copy.depends_on.all()}
    copied_leaf_via_left = children_by_name["left"].depends_on.get()
    copied_leaf_via_right = children_by_name["right"].depends_on.get()
    assert copied_leaf_via_left.pk == copied_leaf_via_right.pk


def test_copy_guard_follows_copy_graph_not_share_graph_for_cycles(alice, make_dummy_divergent_node):
    """Review finding (correctness #1 / security #3): the pre-fix implementation validated
    ``share_dependencies()`` before recursing over the separate ``copy_children`` graph.
    ``DummyDivergentNode`` keeps ``share_edges`` empty throughout, so a pre-flight walk of the
    share graph would have found nothing wrong and let this genuine copy-graph cycle straight
    through into unbounded recursion.
    """
    a = make_dummy_divergent_node(owner=alice, name="a")
    b = make_dummy_divergent_node(owner=alice, name="b")
    a.copy_edges.add(b)
    b.copy_edges.add(a)

    with pytest.raises(CycleError):
        copy_object(a, actor=alice)

    assert DummyDivergentNode.objects.filter(copied_from__isnull=False).count() == 0


def test_copy_guard_follows_copy_graph_not_share_graph_for_depth(alice, make_dummy_divergent_node):
    nodes = [make_dummy_divergent_node(owner=alice, name=f"n{i}") for i in range(MAX_DEPTH + 3)]
    for parent, child in itertools.pairwise(nodes):
        parent.copy_edges.add(child)

    with pytest.raises(DepthExceededError):
        copy_object(nodes[0], actor=alice)

    assert DummyDivergentNode.objects.filter(copied_from__isnull=False).count() == 0


def test_copy_raises_copy_error_when_nested_child_becomes_invisible(
    alice, bob, carol, make_dummy_node
):
    """design.md, "Edge cases": a visible parent whose own child is not visible to the copier
    must fail loudly, distinctly from the root-object 404 — the parent bob is copying very much
    exists and is visible to him; the *reason* the copy cannot finish is nameable, not a guess
    about something that might not exist.
    """
    parent = make_dummy_node(owner=alice, name="parent", visibility=Visibility.SHARED)
    foreign_child = make_dummy_node(owner=carol, name="child", visibility=Visibility.PUBLIC)
    parent.depends_on.add(foreign_child)
    parent.shared_with.add(bob)

    # The child was visible when it was added and shared; it need not stay that way for the
    # container to keep looking fine to bob — this is the "drift after the fact" scenario, not
    # something reachable purely through a single share() call once PUBLIC-widening is guarded.
    foreign_child.visibility = Visibility.PRIVATE
    foreign_child.save(update_fields=["visibility"])

    with pytest.raises(CopyError):
        copy_object(parent, actor=bob)

    assert DummyNode.objects.filter(copied_from__isnull=False).count() == 0
