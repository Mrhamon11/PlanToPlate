"""Tombstone list items whose only content is about to be deleted.

The design mandates two things that pull against each other:

- ``ListItem.recipe`` / ``dish`` / ``ingredient`` are ``SET_NULL`` — deleting a recipe must
  **not** silently delete a line from a list someone is holding in a shop; the line survives as
  a tombstone (design.md, "Models" / "Edge cases").
- ``lists_listitem_has_content`` is a DB ``CheckConstraint`` — a line with no text and no FK is
  invalid (design.md, "Edge cases"; 07.2 DoD).

A *content-only* line — the normal output of ``add_recipe_to_list``, of a dish reference on a
non-shopping list, and of **every** line ``populate_shopping_list`` writes (all
``ingredient``-only) — has no ``text``. The instant its one FK went null, the check constraint
would fail, the delete transaction would abort, and the caller would get a 500 (07.1 review,
blocking finding 1). ``recipes`` / ``meals`` deletion flows only catch ``ProtectedError``, so
this surfaced as a cross-app regression.

**Reconciliation (this supersedes design.md's original bare "just SET_NULL"):** a
``pre_delete`` receiver writes a fallback tombstone ``text`` onto every content-only line that
references the object about to be deleted, *before* Django's collector nulls the FK. The line
then stays constraint-valid, the delete succeeds, and the UI has a string to render. Lines that
already carry their own ``text`` (or other content) are left untouched.

``pre_delete`` runs inside the same transaction as the delete and before the collector's
``SET_NULL`` ``UPDATE``, so the ordering is guaranteed. Registering any receiver also makes
Django emit the signal per-instance for queryset ``.delete()``, so bulk deletes are covered
too.

**App-wide side effect (CO-3):** registering a ``pre_delete`` receiver for Recipe / Dish /
Ingredient disables Django's ``can_fast_delete`` fast path for those three models *everywhere*
and fires one filtered (usually no-op) ``UPDATE`` per instance on every delete of them, even a
large bulk cleanup that touches no list items. Immaterial at 10–20 users; noted so a future
bulk-cleanup author is not surprised by the extra query.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from catalog.models import Ingredient
from lists.models import ListItem
from meals.models import Dish
from recipes.models import Recipe

RECIPE_TOMBSTONE = "(deleted recipe)"
DISH_TOMBSTONE = "(deleted dish)"
INGREDIENT_TOMBSTONE = "(deleted ingredient)"


def _tombstone_content_only(
    instance: Any, *, fk_field: str, other_fks: tuple[str, str], text: str
) -> None:
    """Write ``text`` onto every list item that references ``instance`` through ``fk_field`` and
    would be left with no content once that FK is nulled (no ``text``, and the other two content
    FKs already empty).
    """
    ListItem.objects.filter(
        text="",
        **{fk_field: instance, f"{other_fks[0]}__isnull": True, f"{other_fks[1]}__isnull": True},
    ).update(text=text)


@receiver(pre_delete, sender=Recipe, dispatch_uid="lists.tombstone_recipe_items")
def tombstone_recipe_items(sender: type[Recipe], instance: Recipe, **kwargs: Any) -> None:
    _tombstone_content_only(
        instance, fk_field="recipe", other_fks=("dish", "ingredient"), text=RECIPE_TOMBSTONE
    )


@receiver(pre_delete, sender=Dish, dispatch_uid="lists.tombstone_dish_items")
def tombstone_dish_items(sender: type[Dish], instance: Dish, **kwargs: Any) -> None:
    _tombstone_content_only(
        instance, fk_field="dish", other_fks=("recipe", "ingredient"), text=DISH_TOMBSTONE
    )


@receiver(pre_delete, sender=Ingredient, dispatch_uid="lists.tombstone_ingredient_items")
def tombstone_ingredient_items(
    sender: type[Ingredient], instance: Ingredient, **kwargs: Any
) -> None:
    _tombstone_content_only(
        instance, fk_field="ingredient", other_fks=("recipe", "dish"), text=INGREDIENT_TOMBSTONE
    )
