"""Lists — an ordered, heterogeneous collection of free text, recipes, dishes, or ingredients,
plus the shopping-list behaviour the meal planner drives (``Plan/07-Lists-And-Shopping/
design.md``).

``ListItem`` carries **four explicit nullable foreign keys** rather than one generic
``ContentType`` relation: real database constraints, real indexes, ``select_related`` in one
query, and filters that read plainly, at the cost of one extra column each (design.md,
"Models").

The C8 rule this whole task exists for lives on ``ListItem.source`` / ``generated_from``:
regenerating a meal plan must replace only the items it produced, never a user's hand-typed
lines, and never a *second* plan's items (design.md, "``source`` and ``generated_from``").
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from catalog.models import Ingredient, Unit
from core.models import OwnedModel
from recipes.models import Recipe


class ListKind(models.TextChoices):
    SHOPPING = "SHOPPING", "Shopping list"
    MEAL_PLAN = "MEAL_PLAN", "Meal plan"
    MENU = "MENU", "Menu"
    GENERIC = "GENERIC", "List"


class ItemSource(models.TextChoices):
    MANUAL = "MANUAL", "Added by hand"
    GENERATED = "GENERATED", "Generated from a meal plan"


class List(OwnedModel):
    """A named, ordered list. ``kind`` drives behaviour: a ``SHOPPING`` list expands a dish
    into its ingredients, every other kind keeps a dish or recipe as a single reference line.
    """

    #: A list *references* owned objects through its items, but it does not *contain* them:
    #: sharing a list does not cascade read-grants to the recipes/dishes/ingredients it points
    #: at (a recipient sees only the references already visible to them; the rest render as
    #: tombstones — design.md, "Security notes": "counts must not leak invisible content"), and
    #: copying a list does not deep-copy them. Declared explicitly (``core/README.md``, "Does
    #: this model contain other owned objects?") because ``test_conventions``' relation-walk
    #: reaches ``Recipe``/``Dish``/``Ingredient`` one hop through ``ListItem`` and cannot tell a
    #: pointer collection from a container.
    contains_owned_children = False

    name = models.CharField(max_length=200)
    kind = models.CharField(
        max_length=16,
        choices=ListKind.choices,
        default=ListKind.GENERIC,
        db_index=True,
    )
    #: Marks the one list generated ingredients land on when nothing else is named. A partial
    #: unique constraint (below) guarantees at most one per owner — checking in application code
    #: drifts the first time two requests race (design.md, "The default shopping list").
    is_default_shopping_list = models.BooleanField(default=False)

    class Meta(OwnedModel.Meta):
        ordering = ["name"]
        constraints = [
            *OwnedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["owner"],
                condition=Q(is_default_shopping_list=True),
                name="lists_list_one_default_shopping_per_owner",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        if self.kind == ListKind.SHOPPING:
            return reverse("lists:shopping-detail", args=[self.pk])
        return reverse("lists:list-detail", args=[self.pk])


class ListItem(models.Model):
    """One line of a list.

    Exactly one of ``text`` / ``recipe`` / ``dish`` / ``ingredient`` carries the content — the
    ``lists_listitem_has_content`` check constraint rejects a line with none of them. ``quantity``
    may be set without a ``unit`` (a bare "3 lemons"); ``unit`` without a quantity is allowed
    too.

    ``SET_NULL`` on the three content FKs: deleting a recipe must not silently delete a line
    from a list someone is holding in a shop. The line survives with its text and quantity and
    the UI renders it as a tombstone (design.md, "Models"). ``PROTECT`` on ``unit``, matching
    every other model.

    A *content-only* line (no ``text``, one FK) would violate ``lists_listitem_has_content`` the
    instant that FK went null, aborting the delete. ``lists/signals.py`` closes the gap: a
    ``pre_delete`` receiver on Recipe / Dish / Ingredient writes a fallback tombstone ``text``
    onto referencing content-only lines *before* the FK is nulled, so the row stays valid and
    the constraint still holds. This reconciles the two halves of the design that pulled against
    each other (07.1 review, finding 1).
    """

    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField(default=0)
    is_checked = models.BooleanField(default=False)

    text = models.CharField(max_length=500, blank=True)
    recipe = models.ForeignKey(
        Recipe, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    dish = models.ForeignKey(
        "meals.Dish", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ingredient = models.ForeignKey(
        Ingredient, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True)

    source = models.CharField(
        max_length=16,
        choices=ItemSource.choices,
        default=ItemSource.MANUAL,
        db_index=True,
    )
    #: The meal plan a ``GENERATED`` line came from. Scoping regeneration's delete to this FK is
    #: what lets two plans feed one list without trampling each other (design.md). The
    #: ``"planner.MealPlan"`` string reference resolves to the minimal stub task 07 added;
    #: task 08 fleshes that model out (the string ref itself stays as-is).
    generated_from = models.ForeignKey(
        "planner.MealPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_items",
    )

    class Meta:
        ordering = ["position"]
        constraints = [
            models.CheckConstraint(
                condition=Q(text__gt="")
                | Q(recipe__isnull=False)
                | Q(dish__isnull=False)
                | Q(ingredient__isnull=False),
                name="lists_listitem_has_content",
            )
        ]

    def __str__(self) -> str:
        return self.text or str(self.recipe or self.dish or self.ingredient or "empty item")
