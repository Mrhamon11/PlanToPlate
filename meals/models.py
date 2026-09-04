"""Two ways of grouping recipes: a ``Dish`` (the recipes that make one meal) and a
``RecipeBook`` (a user-organised collection). Both are thin over task 05 — the heavy lifting
(scaling, flattening, the cycle guard) already lives in ``recipes`` (``design.md``, "Goal").

``DishStats`` mirrors ``RecipeStats`` exactly, so both are subclasses of the shared
``core.models.UserObjectStats`` abstract base rather than two hand-copied models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from catalog.models import Tag
from core.models import OwnedModel, UserObjectStats
from meals.managers import DishManager
from recipes.models import Recipe, _copy_or_reference

if TYPE_CHECKING:
    from core.services.copying import Copier


def validate_positive_servings(value: object) -> None:
    """A dish component's ``servings`` is the scale factor applied to that recipe; zero
    contributes nothing to the meal and hides a data-entry mistake, and a negative multiplier
    is meaningless (``design.md``, "Edge cases": "``servings`` of zero: rejected").
    """
    if value is not None and value <= 0:
        raise ValidationError(
            "Servings must be greater than zero.",
            code="non_positive_servings",
        )


class Dish(OwnedModel):
    """A collection of recipes that make one complete meal (glossary)."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="dishes")

    objects = DishManager()

    class Meta(OwnedModel.Meta):
        ordering = ["name"]
        verbose_name_plural = "dishes"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("meals:dish-detail", args=[self.pk])

    def _component_recipes(self) -> list[Recipe]:
        return [component.recipe for component in self.components.all()]

    def share_dependencies(self) -> list[OwnedModel]:
        """The component recipes — sharing a dish grants read on them, which transitively pulls
        in their sub-recipes and ingredients (``design.md``, "Sharing and copying").
        """
        return list(self._component_recipes())

    def copy_children(self, new_obj: Dish, *, copier: Copier) -> None:
        """Deep-copy every component recipe onto ``new_obj``.

        Routed through ``recipes.models._copy_or_reference`` so a recipe the actor has already
        copied — in an earlier operation, or earlier in this one (a dish and a book that share
        a recipe) — is reused rather than copied again (D37).
        """
        for component in self.components.all():
            DishComponent.objects.create(
                dish=new_obj,
                recipe=_copy_or_reference(component.recipe, copier),
                servings=component.servings,
                position=component.position,
            )

    @property
    def total_minutes(self) -> int:
        """Approximate combined cooking time over **every** component, viewer-agnostic.

        Like ``flatten()`` without a ``viewer``, this walks ``self.components.all()``
        unfiltered — a view rendering this for a non-owner would count a component recipe that
        reader cannot see. Serializers and views must use
        ``meals.services.dishes.total_minutes_for`` over ``visible_components`` instead
        (``design.md``, "Security notes").
        """
        from meals.services.dishes import total_minutes

        return total_minutes(self)

    @property
    def roles(self) -> set[str]:
        """The set of component recipe roles over **every** component, viewer-agnostic.

        Same caveat as ``total_minutes``: it does not filter by visibility. Views and
        serializers must use ``meals.services.dishes.roles_for`` over ``visible_components``.
        """
        from meals.services.dishes import roles

        return roles(self)

    def flatten(self, *, exclude_staples: bool = False, viewer: object | None = None) -> list:
        """The dish's combined, aggregated ingredient list — the shopping list's entry point
        (``design.md``, "Derived properties"). Delegates to ``meals.services.dishes``.

        ``viewer`` filters components to recipes that user can see (D31); ``None`` is a
        trusted internal caller and expands every component.
        """
        from meals.services.dishes import flatten_dish

        return flatten_dish(self, exclude_staples=exclude_staples, viewer=viewer)


class DishComponent(models.Model):
    """One recipe within a dish, at a chosen scale.

    ``PROTECT`` on ``recipe`` (unlike ``RecipeBookEntry``'s ``CASCADE``): a recipe used in a
    dish cannot be deleted out from under it — the delete is a 409 naming the dishes
    (``design.md``, "Edge cases").
    """

    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, related_name="components")
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, related_name="dish_components")
    servings = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        validators=[validate_positive_servings],
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(servings__gt=0),
                name="meals_dishcomponent_servings_positive",
            )
        ]

    def __str__(self) -> str:
        return f"{self.servings}× {self.recipe} in {self.dish}"


class DishStats(UserObjectStats):
    """Per-user rating / favourite / times-made for one dish — the same shape as
    ``RecipeStats`` (D3 / C4), on the shared ``UserObjectStats`` base. Accessed lazily through
    ``meals.services.stats``.
    """

    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, related_name="stats")

    class Meta(UserObjectStats.Meta):
        constraints = [
            *UserObjectStats.Meta.constraints,
            models.UniqueConstraint(
                fields=["user", "dish"],
                name="meals_dishstats_unique_user_dish",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.dish}"


class BookOrdering(models.TextChoices):
    MANUAL = "MANUAL", "Manual order"
    NAME = "NAME", "Name"
    RATING = "RATING", "Rating"
    TIME = "TIME", "Total time"
    TIMES_MADE = "TIMES_MADE", "Times made"


class RecipeBook(OwnedModel):
    """A user-organised collection of recipes, grouped into free-text sections (glossary;
    ``design.md``, "RecipeBook").
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    #: The book's preferred sort for its recipe grid — a view-level choice, stored so it
    #: persists between visits (``design.md``: "stored as the book's ``default_ordering``
    #: preference"). ``MANUAL`` honours ``RecipeBookEntry.position``.
    default_ordering = models.CharField(
        max_length=16,
        choices=BookOrdering.choices,
        default=BookOrdering.MANUAL,
    )

    class Meta(OwnedModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("meals:book-detail", args=[self.pk])

    def _entry_recipes(self) -> list[Recipe]:
        return [entry.recipe for entry in self.entries.all()]

    def share_dependencies(self) -> list[OwnedModel]:
        """Every recipe filed in the book (``design.md``, "Sharing and copying")."""
        return list(self._entry_recipes())

    def copy_children(self, new_obj: RecipeBook, *, copier: Copier) -> None:
        """Deep-copy **every** recipe in the book (``design.md``: "copying a 60-recipe book
        silently creates 60 dependencies on another user's data ... task 03 chose independence
        over cleverness"). ``_copy_or_reference`` reuses an already-made copy where one exists
        (D37).
        """
        for entry in self.entries.all():
            RecipeBookEntry.objects.create(
                book=new_obj,
                recipe=_copy_or_reference(entry.recipe, copier),
                section=entry.section,
                position=entry.position,
            )


class RecipeBookEntry(models.Model):
    """One filing of a recipe in a book.

    ``CASCADE`` on ``recipe`` (unlike ``DishComponent``'s ``PROTECT``): removing a recipe from a
    book is a filing change, not data loss, so a deleted recipe should quietly leave its books
    rather than block its own deletion (``design.md``, "RecipeBook").
    """

    book = models.ForeignKey(RecipeBook, on_delete=models.CASCADE, related_name="entries")
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="book_entries")
    section = models.CharField(max_length=100, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["section", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "recipe"],
                name="meals_recipebookentry_unique_book_recipe",
            )
        ]

    def __str__(self) -> str:
        return f"{self.recipe} in {self.book}"
