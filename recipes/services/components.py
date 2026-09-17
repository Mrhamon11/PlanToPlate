"""Parsing and persisting a recipe's component rows from the HTML editor
(``Plan/05-Recipes/design.md``, "UI": "Recipe form").

The REST path writes components through ``RecipeSerializer``; this is the HTML form's
equivalent. Both converge on ``recipes.services.graph.assert_no_cycle`` — the cycle guard has
one implementation and *every* write path calls it (design.md, "The cycle guard": "three
write paths ... a guard on one path is not a guard").

The typeahead helpers here are the other half of the same contract: the ingredient and
sub-recipe pickers only ever surface objects ``visible_to`` the requester, and the sub-recipe
picker additionally drops any candidate that would create a cycle — so an illegal choice is
never offered, not merely rejected on submit (design.md, "Security notes").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q

from catalog.exceptions import IncompatibleUnits
from catalog.models import Ingredient, Unit
from catalog.services.units import convert
from recipes.models import Recipe, RecipeComponent
from recipes.services.graph import GraphError, assert_no_cycle

if TYPE_CHECKING:
    from django.http import QueryDict

_TYPEAHEAD_LIMIT = 20


class ComponentError(Exception):
    """A submitted component row cannot be saved — a bad quantity, an ingredient or sub-recipe
    the requester cannot see, an unscalable sub-recipe unit, or a graph the cycle guard
    rejects. The message is written for the cook and is safe to render back on the form.
    """


@dataclass(frozen=True)
class ComponentDraft:
    """One validated, not-yet-persisted component row."""

    ingredient: Ingredient | None
    sub_recipe: Recipe | None
    quantity: Decimal
    unit: Unit
    note: str = ""


def parse_component_drafts(data: QueryDict, *, user) -> list[ComponentDraft]:
    """Turn the editor's parallel ``component_*`` POST arrays into validated drafts.

    A row with neither a reference nor a quantity is treated as an untouched blank and
    skipped. Every remaining row must name a visible ingredient *or* a visible sub-recipe (the
    flagship IDOR defence), a positive quantity, and a real unit. Raises ``ComponentError`` on
    the first problem; a recipe with no usable row at all is also an error.
    """
    kinds = data.getlist("component_kind")
    refs = data.getlist("component_ref")
    quantities = data.getlist("component_quantity")
    units = data.getlist("component_unit")
    notes = data.getlist("component_note")

    drafts: list[ComponentDraft] = []
    for index in range(len(kinds)):
        kind = (kinds[index] or "").strip()
        ref = _at(refs, index)
        raw_quantity = _at(quantities, index)
        raw_unit = _at(units, index)
        note = _at(notes, index)

        if not ref and not raw_quantity:
            continue

        ingredient = sub_recipe = None
        if kind == "sub_recipe":
            sub_recipe = _resolve_visible(Recipe, ref, user, "sub-recipe")
        else:
            ingredient = _resolve_visible(Ingredient, ref, user, "ingredient")

        quantity = _parse_quantity(raw_quantity)
        unit = _resolve_unit(raw_unit)

        if sub_recipe is not None:
            assert_sub_recipe_unit_scalable(sub_recipe, quantity, unit)

        drafts.append(ComponentDraft(ingredient, sub_recipe, quantity, unit, note))

    if not drafts:
        raise ComponentError("Add at least one ingredient or sub-recipe.")
    return drafts


def assert_drafts_acyclic(recipe: Recipe, drafts: list[ComponentDraft]) -> None:
    """Run the cycle / depth guard for every sub-recipe draft before anything is written."""
    for draft in drafts:
        if draft.sub_recipe is not None:
            try:
                assert_no_cycle(recipe, draft.sub_recipe)
            except GraphError as exc:
                raise ComponentError(str(exc)) from exc


@transaction.atomic
def replace_components(recipe: Recipe, drafts: list[ComponentDraft]) -> None:
    """Replace ``recipe``'s component set with ``drafts``, positioned in list order, inside one
    transaction (replace-the-set semantics, matching ``RecipeSerializer``). The cycle guard
    runs first, so a rejected write leaves the existing components untouched.
    """
    assert_drafts_acyclic(recipe, drafts)
    recipe.components.all().delete()
    for position, draft in enumerate(drafts):
        RecipeComponent.objects.create(
            recipe=recipe,
            ingredient=draft.ingredient,
            sub_recipe=draft.sub_recipe,
            quantity=draft.quantity,
            unit=draft.unit,
            note=draft.note,
            position=position,
        )


def ingredient_choices(
    user, query: str | None, *, limit: int = _TYPEAHEAD_LIMIT
) -> list[Ingredient]:
    """Ingredients ``visible_to(user)`` whose name matches ``query`` — the typeahead never
    surfaces an invisible object's name (design.md, "Security notes")."""
    queryset = Ingredient.objects.visible_to(user).select_related("default_unit")
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    return list(queryset.order_by("name")[:limit])


def sub_recipe_choices(
    user, query: str | None, *, recipe: Recipe | None = None, limit: int = _TYPEAHEAD_LIMIT
) -> list[Recipe]:
    """Recipes ``visible_to(user)`` whose name matches ``query``, minus ``recipe`` itself and
    minus every candidate that ``assert_no_cycle`` would reject — a cycle-creating choice is
    never offered, not merely refused on submit (design.md, "Security notes";
    ``test_subrecipe_typeahead_excludes_cycles``).

    ``recipe=None`` (the create form) needs no cycle filtering: a recipe that does not exist
    yet cannot be part of any cycle.
    """
    queryset = Recipe.objects.visible_to(user).select_related("yield_unit")
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    if recipe is not None and recipe.pk is not None:
        queryset = queryset.exclude(pk=recipe.pk)

    if recipe is None or recipe.pk is None:
        return list(queryset.order_by("name")[:limit])

    allowed: list[Recipe] = []
    for candidate in queryset.order_by("name"):
        try:
            assert_no_cycle(recipe, candidate)
        except GraphError:
            continue
        allowed.append(candidate)
        if len(allowed) >= limit:
            break
    return allowed


def _at(values: list[str], index: int) -> str:
    return (values[index] if index < len(values) else "").strip()


def _resolve_visible(model: type, raw: str, user, label: str):
    if not raw.isdigit():
        raise ComponentError(f"Choose a valid {label} for every row.")
    obj = model.objects.visible_to(user).filter(pk=int(raw)).first()
    if obj is None:
        raise ComponentError(f"One of the {label}s you chose is not available to you.")
    return obj


def _resolve_unit(raw: str) -> Unit:
    if not raw.isdigit():
        raise ComponentError("Choose a unit for every row.")
    unit = Unit.objects.filter(pk=int(raw)).first()
    if unit is None:
        raise ComponentError("Choose a valid unit for every row.")
    return unit


def _parse_quantity(raw: str) -> Decimal:
    try:
        quantity = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ComponentError("Every quantity must be a number.") from None
    if not quantity.is_finite() or quantity <= 0:
        raise ComponentError("Every quantity must be greater than zero.")
    return quantity


def neutralize_protect_blockers_for_owner_deletion(owner) -> None:
    """Clear every ``RecipeComponent.ingredient`` / ``sub_recipe`` ``PROTECT`` blocker that
    ``accounts.services.delete_user`` would otherwise hit deleting ``owner`` (``ARCHITECTURE.md``
    D53) — called from that service's pre-pass, before ``owner.delete()`` runs.

    A ``RecipeComponent`` only blocks the cascade when the object it references (``ingredient``
    or ``sub_recipe``) belongs to ``owner`` — that is what is about to be deleted. Two shapes:

    - **Self-owned**: the component's own ``recipe`` also belongs to ``owner``, so the
      component row is cascading away in the very same ``owner.delete()`` (its ``recipe`` FK is
      ``CASCADE``). Django's collector does not know that yet when it checks ``PROTECT``, so
      these rows are deleted outright here, ahead of the cascade — nothing is lost that was not
      already going away.
    - **Cross-owner (bystander)**: the component's ``recipe`` belongs to someone else, who is
      not being deleted and whose recipe must survive. The referencing field is set to ``None``
      instead (the row's XOR-or-neither constraint allows this — see ``RecipeComponent``'s
      docstring), the same graceful-degradation pattern ``ListItem.recipe``/``dish``/
      ``ingredient`` already use for a recipe gone private (D31). Every read path that flattens
      or displays a component already tolerates both fields being ``None``.

    The self-owned delete must run first: once those rows are gone, a plain
    ``filter(ingredient__owner=owner)`` / ``filter(sub_recipe__owner=owner)`` update only ever
    matches the remaining cross-owner rows.
    """
    RecipeComponent.objects.filter(recipe__owner=owner).filter(
        Q(ingredient__owner=owner) | Q(sub_recipe__owner=owner)
    ).delete()
    RecipeComponent.objects.filter(ingredient__owner=owner).update(ingredient=None)
    RecipeComponent.objects.filter(sub_recipe__owner=owner).update(sub_recipe=None)


def assert_sub_recipe_unit_scalable(sub_recipe: Recipe, quantity: Decimal, unit: Unit) -> None:
    """Raise ``ComponentError`` if a sub-recipe component called for in ``unit`` cannot be
    scaled to ``sub_recipe.yield_unit`` — the flattener divides by
    ``convert(quantity, unit, yield_unit)``, so an incompatible pair produces a row that only
    blows up later in ``flatten``.

    The single implementation of this rule (CLAUDE.md §6). The REST path
    (``recipes/serializers.py``), the importer (``core/services/importer.py``) and the admin
    forms (``recipes/admin.py``) all enforce the same check on their own write paths.
    """
    try:
        convert(quantity, unit, sub_recipe.yield_unit)
    except IncompatibleUnits as exc:
        raise ComponentError(
            f"Sub-recipe '{sub_recipe.name}' is called for in {unit.name}, but it yields "
            f"{sub_recipe.yield_unit.name} — those measure different things, so there is no "
            "way to scale it. Use a unit compatible with the sub-recipe's yield."
        ) from exc


__all__ = [
    "ComponentDraft",
    "ComponentError",
    "assert_drafts_acyclic",
    "assert_sub_recipe_unit_scalable",
    "ingredient_choices",
    "neutralize_protect_blockers_for_owner_deletion",
    "parse_component_drafts",
    "replace_components",
    "sub_recipe_choices",
]
