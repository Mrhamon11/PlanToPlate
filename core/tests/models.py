"""Throwaway concrete ``OwnedModel`` subclasses used only by core's own test suite.

There is no real domain model yet (task 04 adds the first one). Building and testing
``OwnedModel``, ``OwnedQuerySet``/``OwnedManager``, the permission classes, and the dependency
graph walker against a stand-in here keeps task 03 independent of task 04, per
``Plan/03-Ownership-And-Sharing/tasks.md``. Registered as their own app,
``core_test_fixtures`` (``core/tests/apps.py``), included in ``INSTALLED_APPS`` only by
``config/settings/test.py`` — these tables never exist outside the test database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

from core.models import OwnedModel

if TYPE_CHECKING:
    from core.services.copying import Copier


class DummyOwned(OwnedModel):
    """A minimal, leafless concrete ``OwnedModel`` — exercises the model/visibility layer."""

    name = models.CharField(max_length=100, default="dummy")

    def __str__(self) -> str:
        return self.name


class DummyNode(OwnedModel):
    """A concrete ``OwnedModel`` whose ``share_dependencies()`` points at other ``DummyNode``
    rows, used to exercise ``core.services.graph.walk_dependencies`` (transitive traversal,
    the cycle guard, the depth cap) without a real container/child pair from a later task.

    ``copy_children()`` (03.6) reuses the same ``depends_on`` relation as its child set, deep
    copying each dependency and re-pointing the copy at the new owner — exercising the copy
    service's depth cap/cycle guard and atomicity without a real container/child pair either.
    """

    name = models.CharField(max_length=100, default="node")
    depends_on = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="depended_on_by",
    )

    def __str__(self) -> str:
        return self.name

    def share_dependencies(self) -> list[DummyNode]:
        return list(self.depends_on.all())

    def copy_children(self, new_obj: DummyNode, *, copier: Copier) -> None:
        children = [copier.copy(dependency) for dependency in self.depends_on.all()]
        if children:
            new_obj.depends_on.set(children)


class DummyDivergentNode(OwnedModel):
    """Deliberately gives ``share_dependencies()`` and ``copy_children()`` different edge sets,
    reproducing the exact shape a real container/child pair can take (a Recipe whose
    ``copy_children`` reaches ``RecipeComponent.sub_recipe`` while ``share_dependencies``
    returns something else, or nothing).

    Exercises that the copy service's cycle guard and depth cap apply to the graph it actually
    walks (``copy_edges``, via ``copy_children``) rather than the sharing graph
    (``share_edges``, via ``share_dependencies``) — the two must be able to diverge completely,
    including one being cyclic/deep while the other is empty, without weakening the copy
    service's guarantees.
    """

    name = models.CharField(max_length=100, default="divergent")
    share_edges = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="shared_by"
    )
    copy_edges = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="copied_by"
    )

    def __str__(self) -> str:
        return self.name

    def share_dependencies(self) -> list[DummyDivergentNode]:
        return list(self.share_edges.all())

    def copy_children(self, new_obj: DummyDivergentNode, *, copier: Copier) -> None:
        children = [copier.copy(dependency) for dependency in self.copy_edges.all()]
        if children:
            new_obj.copy_edges.set(children)
