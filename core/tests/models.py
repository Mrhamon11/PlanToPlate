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


class DummyContainer(OwnedModel):
    """A concrete ``OwnedModel`` that reaches its children only through the *reverse* side of a
    plain, non-owned join model — the real shape every planned container takes (task 05's
    ``RecipeComponent.recipe``/``.sub_recipe``, task 06's ``DishComponent``,
    ``RecipeBookEntry``): ``DummyContainer`` itself declares no forward field pointing at
    another ``OwnedModel`` at all, only a reverse accessor (``components``) into
    ``DummyComponent``, which is *not* an ``OwnedModel`` and forward-references
    ``DummyContainer`` again for its ``child``.

    Exists so ``core/tests/test_conventions.py``'s hooks guard can be proven against this shape
    directly, rather than only against ``DummyNode``'s self-M2M (a forward relation, which a
    detector that only looks at forward fields would already catch — the container shape below
    is exactly what such a detector cannot see).
    """

    name = models.CharField(max_length=100, default="container")

    def __str__(self) -> str:
        return self.name

    def share_dependencies(self) -> list[DummyContainer]:
        return [component.child for component in self.components.all()]

    def copy_children(self, new_obj: DummyContainer, *, copier: Copier) -> None:
        for component in self.components.all():
            DummyComponent.objects.create(container=new_obj, child=copier.copy(component.child))


class DummyComponent(models.Model):
    """Plain (non-owned) join model mirroring ``RecipeComponent``'s shape: a container FK plus
    a child FK to an ``OwnedModel``, neither of which is itself owned.
    """

    container = models.ForeignKey(
        DummyContainer, on_delete=models.CASCADE, related_name="components"
    )
    child = models.ForeignKey(DummyContainer, on_delete=models.CASCADE, related_name="+")

    def __str__(self) -> str:
        return f"{self.container_id} -> {self.child_id}"


class DummyJoinedContainer(OwnedModel):
    """A real container reached through a *two-parent* join model (``DummyJoinedComponent``)
    whose other FK points at a different ``OwnedModel`` entirely (``DummyJoinedLeaf``) — the
    exact ``RecipeComponent.recipe`` / ``.ingredient`` shape (``Plan/05-Recipes/design.md``)
    ``DummyContainer``/``DummyComponent`` above does not reproduce, since both of
    ``DummyComponent``'s FKs point back at ``DummyContainer`` itself.
    """

    name = models.CharField(max_length=100, default="joined-container")

    def __str__(self) -> str:
        return self.name

    def share_dependencies(self) -> list[DummyJoinedLeaf]:
        return [component.leaf for component in self.components.all()]

    def copy_children(self, new_obj: DummyJoinedContainer, *, copier: Copier) -> None:
        for component in self.components.all():
            DummyJoinedComponent.objects.create(container=new_obj, leaf=copier.copy(component.leaf))


class DummyJoinedLeaf(OwnedModel):
    """A genuine leaf reached only through the *other* FK of the same two-parent join model as
    ``DummyJoinedContainer`` — ``core/tests/test_conventions.py``'s hooks guard cannot tell
    this apart from a container by walking the join model's fields alone (both
    ``DummyJoinedComponent.container`` and ``.leaf`` are forward FKs to an ``OwnedModel``), so
    it relies on the explicit ``contains_owned_children = False`` opt-out below rather than on
    a heuristic that cannot resolve the ambiguity.
    """

    name = models.CharField(max_length=100, default="joined-leaf")
    contains_owned_children = False

    def __str__(self) -> str:
        return self.name


class DummyJoinedComponent(models.Model):
    """Plain (non-owned) two-parent join model: one FK to the container, one FK to a different
    ``OwnedModel`` leaf — unlike ``DummyComponent``, whose two FKs both point at
    ``DummyContainer``, this reproduces ``RecipeComponent``'s actual shape.
    """

    container = models.ForeignKey(
        DummyJoinedContainer, on_delete=models.CASCADE, related_name="components"
    )
    # Unlike DummyComponent.child's related_name="+" above, this FK keeps its reverse accessor
    # (mirroring Plan/05-Recipes/design.md's Ingredient, which needs one) -- that reverse
    # relation into DummyJoinedComponent is exactly what makes DummyJoinedLeaf visible to
    # _declares_relation_to_owned_model's join-model walk at all, which is the false positive
    # this fixture pair exists to reproduce.
    leaf = models.ForeignKey(DummyJoinedLeaf, on_delete=models.CASCADE, related_name="components")

    def __str__(self) -> str:
        return f"{self.container_id} -> {self.leaf_id}"
