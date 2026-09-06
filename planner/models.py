"""The meal planner's models land in **task 08** (``Plan/08-Meal-Planner/design.md``).

``MealPlan`` is defined here now, as a bare ``OwnedModel``, only because task 07's
``lists.ListItem.generated_from`` is a real foreign key to it (``Plan/07-Lists-And-Shopping/
design.md``, "``source`` and ``generated_from``") and Django's system checks reject a lazy
reference whose target model does not exist (``fields.E300`` / ``fields.E307``), so
``manage.py check`` and the whole test suite stay red without it. Task 08 adds the real fields
(``start_date``, ``days``, ``profile``, ``profile_snapshot``, ``seed``, ``shopping_list``, …),
``MealPlanProfile``, ``MealPlanEntry``, and the generator.
"""

from __future__ import annotations

from django.db import models

from core.models import OwnedModel


class MealPlan(OwnedModel):
    """A week of planned meals. Fleshed out in task 08 — see this module's docstring."""

    #: ``test_conventions``' relation-walk reaches ``Recipe`` / ``Dish`` / ``Ingredient`` /
    #: ``List`` one hop out through ``lists.ListItem.generated_from``'s reverse relation and
    #: cannot tell "items that point back at me" from "my children" — the same false positive
    #: ``Ingredient`` carries (``core/README.md``, "a leaf reached through the same join
    #: model"). This stub genuinely has no owned children. **Task 08 must re-evaluate** once it
    #: adds ``entries`` / ``shopping_list`` and decides whether sharing a plan cascades.
    contains_owned_children = False

    name = models.CharField(max_length=200, blank=True)

    class Meta(OwnedModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"Meal plan #{self.pk}"
