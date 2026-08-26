"""The ownership/visibility keystone every domain model inherits (design.md, "OwnedModel").

``OwnedModel`` itself has no concrete rows — it is abstract, so this app declares zero real
models. Every app from task 04 onward subclasses it for its user-creatable models (Ingredient,
Recipe, Dish, RecipeBook, List, MealPlan, ...); ``core/tests/models.py`` supplies throwaway
subclasses so this task's own suite can exercise the machinery before any of those exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.managers import OwnedManager

if TYPE_CHECKING:
    from core.services.copying import Copier


class Visibility(models.TextChoices):
    PRIVATE = "PRIVATE", "Private"
    SHARED = "SHARED", "Shared with specific people"
    PUBLIC = "PUBLIC", "Everyone with an account"


class OwnedModel(models.Model):
    """Abstract base for every user-creatable object (MILESTONES.md section 4).

    ``owner`` is nullable only for ``is_system`` rows (seeded, globally-readable, writable by
    nobody through the API) — the check constraint below enforces that exclusive-or at the
    database level rather than leaving it as an application-level convention that can drift.

    A concrete M2M (``shared_with``) is used instead of a generic ``ContentType``-based share
    table so each concrete model gets its own join table with real foreign keys and indexes —
    see design.md, "Why a concrete M2M on an abstract base".
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        null=True,
        blank=True,
    )
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        db_index=True,
    )
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="shared_%(class)ss",
    )
    is_system = models.BooleanField(default=False, db_index=True)
    notes = models.TextField(blank=True)
    copied_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="copies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OwnedManager()

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=Q(is_system=True, owner__isnull=True)
                | Q(is_system=False, owner__isnull=False),
                name="%(app_label)s_%(class)s_owner_xor_system",
            )
        ]

    def share_dependencies(self) -> list[OwnedModel]:
        """Other owned objects this one references, whose read-access must cascade when this
        object is shared (design.md, "The cascade"; walked by
        ``core.services.graph.walk_dependencies``). A model that contains others — a Dish
        holding Recipes, a Recipe holding sub-Recipes — overrides this. The default is "none":
        most owned models are leaves.
        """
        return []

    def copy_children(self, new_obj: OwnedModel, *, copier: Copier) -> None:
        """Deep-copy this object's children onto ``new_obj`` (core/services/copying.py, 03.6).

        Call ``copier.copy(dependency)`` for each child — never ``copy_object`` directly. The
        ``Copier`` is what gives the whole operation its cycle guard, depth cap, and
        memoization: a child reachable through two different paths (a diamond in the graph) is
        copied exactly once and re-attached in both places, rather than copied once per path.
        The default does nothing — most owned models are leaves.
        """
        return None
