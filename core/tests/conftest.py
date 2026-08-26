"""Fixtures shared by core's ownership/visibility/permission/graph tests.

Standard cast, per Plan/03-Ownership-And-Sharing/test-plan.md: ``alice`` (owner), ``bob``
(shared-with), ``carol`` (unrelated), ``admin`` (superuser — included because "even a
superuser cannot get a system object through editable_by").
"""

from __future__ import annotations

import pytest

from core.models import Visibility
from core.tests.models import (
    DummyComponent,
    DummyContainer,
    DummyDivergentNode,
    DummyJoinedComponent,
    DummyJoinedContainer,
    DummyJoinedLeaf,
    DummyNode,
    DummyOwned,
)


@pytest.fixture
def alice(user_factory):
    return user_factory(username="alice")


@pytest.fixture
def bob(user_factory):
    return user_factory(username="bob")


@pytest.fixture
def carol(user_factory):
    return user_factory(username="carol")


@pytest.fixture
def admin(user_factory):
    return user_factory(username="admin", is_staff=True, is_superuser=True)


@pytest.fixture
def make_dummy(db):
    """Factory fixture: build a persisted ``DummyOwned`` with sane defaults, overridable."""

    def _make(**kwargs) -> DummyOwned:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyOwned.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_node(db):
    """Factory fixture: build a persisted ``DummyNode``, for the dependency-graph tests."""

    def _make(**kwargs) -> DummyNode:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyNode.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_divergent_node(db):
    """Factory fixture: build a persisted ``DummyDivergentNode``, whose ``share_edges`` and
    ``copy_edges`` are independent relations — for tests proving the copy service's guard
    applies to the graph it actually copies, not the sharing graph.
    """

    def _make(**kwargs) -> DummyDivergentNode:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyDivergentNode.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_container(db):
    """Factory fixture: build a persisted ``DummyContainer``, whose children are reached only
    through the reverse side of ``DummyComponent`` (the real task-05+ container shape).
    """

    def _make(**kwargs) -> DummyContainer:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyContainer.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_component(db):
    """Factory fixture: build a persisted ``DummyComponent`` linking a ``DummyContainer`` to a
    child ``DummyContainer`` through the plain, non-owned join model.
    """

    def _make(**kwargs) -> DummyComponent:
        return DummyComponent.objects.create(**kwargs)

    return _make


@pytest.fixture
def make_dummy_joined_container(db):
    """Factory fixture: build a persisted ``DummyJoinedContainer`` — the real container half of
    the two-parent join model shape (``RecipeComponent.recipe``/``.ingredient``).
    """

    def _make(**kwargs) -> DummyJoinedContainer:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyJoinedContainer.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_joined_leaf(db):
    """Factory fixture: build a persisted ``DummyJoinedLeaf`` — the genuine-leaf half of the
    same two-parent join model shape, reached only through the join model's *other* FK.
    """

    def _make(**kwargs) -> DummyJoinedLeaf:
        defaults = {"visibility": Visibility.PRIVATE, "is_system": False}
        defaults.update(kwargs)
        return DummyJoinedLeaf.objects.create(**defaults)

    return _make


@pytest.fixture
def make_dummy_joined_component(db):
    """Factory fixture: build a persisted ``DummyJoinedComponent`` linking a
    ``DummyJoinedContainer`` to a ``DummyJoinedLeaf`` through the plain, non-owned,
    two-parent join model.
    """

    def _make(**kwargs) -> DummyJoinedComponent:
        return DummyJoinedComponent.objects.create(**kwargs)

    return _make
