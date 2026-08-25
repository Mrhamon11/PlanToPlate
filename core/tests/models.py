"""Throwaway concrete ``OwnedModel`` subclasses used only by core's own test suite.

There is no real domain model yet (task 04 adds the first one). Building and testing
``OwnedModel``, ``OwnedQuerySet``/``OwnedManager``, the permission classes, and the dependency
graph walker against a stand-in here keeps task 03 independent of task 04, per
``Plan/03-Ownership-And-Sharing/tasks.md``. Registered as their own app,
``core_test_fixtures`` (``core/tests/apps.py``), included in ``INSTALLED_APPS`` only by
``config/settings/test.py`` — these tables never exist outside the test database.
"""

from __future__ import annotations

from django.db import models

from core.models import OwnedModel


class DummyOwned(OwnedModel):
    """A minimal, leafless concrete ``OwnedModel`` — exercises the model/visibility layer."""

    name = models.CharField(max_length=100, default="dummy")

    def __str__(self) -> str:
        return self.name


class DummyNode(OwnedModel):
    """A concrete ``OwnedModel`` whose ``share_dependencies()`` points at other ``DummyNode``
    rows, used to exercise ``core.services.graph.walk_dependencies`` (transitive traversal,
    the cycle guard, the depth cap) without a real container/child pair from a later task.
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
