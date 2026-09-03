"""Scale and flatten — the most load-bearing service in the project (design.md, "Scaling and
flattening"). The shopping list (07) and the meal planner (08) both stand on it.

``scale`` returns a recipe's components with every quantity multiplied, persisting nothing.

``flatten`` recursively expands a recipe into a flat list of ingredient lines, scaling each
sub-recipe by ``requested_quantity / sub_recipe.yield_quantity`` (converting units within the
dimension first — this is the step ``yield_quantity`` exists for), guarded against cycles and
capped at ``MAX_DEPTH`` by reusing ``recipes.services.graph``.

``aggregate`` groups those lines by ``(ingredient, compatible-unit)`` and sums them in base
units. Lines whose dimensions cannot be reconciled without inventing a density — 200 g flour
and 2 cups flour with no density, or two counted units with no shared family (D34) — stay
**separate**. Two honest lines beat one fabricated number.

Every quantity here is ``Decimal``. ``float`` never appears.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from catalog.exceptions import IncompatibleUnits
from catalog.models import Dimension, Unit
from catalog.services.units import convert
from recipes.services.graph import MAX_DEPTH, CycleError, DepthExceededError

if TYPE_CHECKING:
    from catalog.models import Ingredient
    from recipes.models import Recipe, RecipeComponent

ONE = Decimal(1)

_FRIENDLY_LOW = Decimal(1)
_FRIENDLY_HIGH = Decimal(1000)


def _factor_as_decimal(value: Decimal | int | str) -> Decimal:
    """Coerce a scaling factor to ``Decimal``, refusing a ``float`` at the boundary rather than
    silently coercing it — ``Decimal(0.1)`` carries the binary-float rounding error the "Decimal
    end to end" DoD exists to keep out of a scaled quantity (task 05 review NB2, mirroring
    ``catalog.services.units._as_decimal``). A caller holding a float converts on their side of
    the seam (``Decimal(str(x))``), or better, never has one.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError(
            f"factor must be a Decimal, int, or str — got float {value!r}. "
            "Binary float rounding corrupts kitchen quantities; convert before calling."
        )
    return Decimal(str(value))


class FlattenError(Exception):
    """A recipe cannot be flattened: a sub-recipe has a non-positive yield, or its yield is
    measured in a dimension the calling quantity cannot be converted to (design.md, "Edge
    cases"). Distinct from ``graph.GraphError`` (cycles / depth), which flatten re-raises as-is.
    """


@dataclass(frozen=True)
class FlatLine:
    """One ingredient's contribution to a flattened recipe.

    ``from_recipes`` is the chain of recipe names from the flatten root down to the recipe that
    directly lists this ingredient — the provenance behind "1 cup — from Marinara, Meatballs".
    """

    ingredient: Ingredient
    quantity: Decimal
    unit: Unit
    from_recipes: tuple[str, ...]


def scale(recipe: Recipe, factor: Decimal) -> list[RecipeComponent]:
    """``recipe``'s components with every quantity multiplied by ``factor``, as **unsaved**
    instances. Nothing is persisted — this backs the "cook this for 8 instead of 4" preview
    that must change nothing in the database (design.md, "API": ``/scaled/``).
    """
    from recipes.models import RecipeComponent

    factor = _factor_as_decimal(factor)
    scaled: list[RecipeComponent] = []
    for component in recipe.components.all():
        scaled.append(
            RecipeComponent(
                recipe=recipe,
                ingredient=component.ingredient if component.ingredient_id else None,
                sub_recipe=component.sub_recipe if component.sub_recipe_id else None,
                quantity=component.quantity * factor,
                unit=component.unit,
                position=component.position,
                note=component.note,
            )
        )
    return scaled


def flatten(
    recipe: Recipe,
    *,
    factor: Decimal = ONE,
    exclude_staples: bool = False,
) -> list[FlatLine]:
    """Expand ``recipe`` into a flat list of ``FlatLine``, one per ingredient occurrence,
    every quantity scaled by ``factor`` (and, for a sub-recipe, by its yield factor).

    Not aggregated — a flat recipe returns its own components unchanged. Call ``aggregate`` on
    the result to merge same-ingredient lines. Raises ``CycleError`` / ``DepthExceededError``
    on a malformed graph and ``FlattenError`` on an unscalable sub-recipe.

    If ``recipe`` already carries the full component graph (it came from
    ``Recipe.objects.with_component_graph()``), that prefetch is reused as-is; otherwise the
    recipe is re-fetched with the prefetch applied. A caller flattening many recipes — the meal
    planner over a week of dinners — should prefetch once and pass the prefetched instances in.
    """
    factor = _factor_as_decimal(factor)
    if _has_component_graph(recipe):
        prefetched = recipe
    else:
        from recipes.models import Recipe as RecipeModel

        prefetched = RecipeModel.objects.with_component_graph().get(pk=recipe.pk)
    lines: list[FlatLine] = []
    _flatten_into(
        prefetched,
        factor,
        name_path=(prefetched.name,),
        id_path=(prefetched.pk,),
        depth=0,
        exclude_staples=exclude_staples,
        out=lines,
    )
    return lines


def _has_component_graph(recipe: Recipe) -> bool:
    """True if ``recipe`` was loaded through ``Recipe.objects.with_component_graph()`` — its
    ``components`` (and, by that queryset's construction, every nested sub-recipe level) are
    already in memory, so ``flatten`` must not re-fetch and discard the caller's prefetch.
    """
    return "components" in getattr(recipe, "_prefetched_objects_cache", {})


def _flatten_into(
    recipe: Recipe,
    factor: Decimal,
    *,
    name_path: tuple[str, ...],
    id_path: tuple[object, ...],
    depth: int,
    exclude_staples: bool,
    out: list[FlatLine],
) -> None:
    for component in recipe.components.all():
        if component.ingredient_id:
            ingredient = component.ingredient
            if exclude_staples and ingredient.is_staple:
                continue
            out.append(
                FlatLine(
                    ingredient=ingredient,
                    quantity=component.quantity * factor,
                    unit=component.unit,
                    from_recipes=name_path,
                )
            )
            continue

        sub_recipe = component.sub_recipe
        if sub_recipe.pk in id_path:
            raise CycleError([*name_path, sub_recipe.name])
        if depth + 1 > MAX_DEPTH:
            raise DepthExceededError([*name_path, sub_recipe.name])

        sub_factor = _sub_recipe_factor(component, sub_recipe)
        _flatten_into(
            sub_recipe,
            factor * sub_factor,
            name_path=(*name_path, sub_recipe.name),
            id_path=(*id_path, sub_recipe.pk),
            depth=depth + 1,
            exclude_staples=exclude_staples,
            out=out,
        )


def _sub_recipe_factor(component: RecipeComponent, sub_recipe: Recipe) -> Decimal:
    """``convert(component.quantity, component.unit, sub.yield_unit) / sub.yield_quantity`` —
    how many batches of ``sub_recipe`` the parent's line calls for (design.md, step 3).
    """
    if sub_recipe.yield_quantity is None or sub_recipe.yield_quantity <= 0:
        raise FlattenError(
            f"Cannot flatten '{sub_recipe.name}': its yield is not a positive quantity, so "
            "there is no way to scale it."
        )
    try:
        requested = convert(component.quantity, component.unit, sub_recipe.yield_unit, None)
    except IncompatibleUnits as exc:
        raise FlattenError(
            f"Cannot flatten '{sub_recipe.name}': it is called for in "
            f"{component.unit.name}, but the recipe yields {sub_recipe.yield_unit.name}, and "
            "those measure different things — there is no way to convert between them."
        ) from exc
    return Decimal(requested) / sub_recipe.yield_quantity


def aggregate(lines: Iterable[FlatLine]) -> list[FlatLine]:
    """Merge ``lines`` by ``(ingredient, compatible unit)``, summing in base units and
    converting the total to a human-friendly unit.

    Lines for the same ingredient whose units cannot be converted into one another without
    fabricating data (mass vs volume with no density; two counted units with no shared family,
    D34) stay as separate lines, each labelled with its own provenance.
    """
    groups: dict[object, list[FlatLine]] = {}
    order: list[object] = []
    for line in lines:
        key = line.ingredient.pk
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(line)

    # One ``Unit`` fetch per dimension for the whole aggregation, not one per line that needs a
    # friendlier unit — ``aggregate`` is the shopping-list hot path (task 05 review, NB1).
    unit_cache: dict[str, list[Unit]] = {}
    result: list[FlatLine] = []
    for key in order:
        result.extend(_aggregate_one_ingredient(groups[key], unit_cache))
    return result


class _Bucket:
    """A running total for one ingredient in one unit that everything added so far converts
    into cleanly."""

    def __init__(self, ingredient: Ingredient, unit: Unit) -> None:
        self.ingredient = ingredient
        self.unit = unit
        self.total = Decimal(0)
        self.from_recipes: list[str] = []

    def add(self, quantity: Decimal, unit: Unit) -> bool:
        try:
            converted = convert(quantity, unit, self.unit, self.ingredient)
        except IncompatibleUnits:
            return False
        self.total += Decimal(converted)
        return True

    def merge_provenance(self, names: Iterable[str]) -> None:
        for name in names:
            if name not in self.from_recipes:
                self.from_recipes.append(name)


def _aggregate_one_ingredient(
    lines: list[FlatLine],
    unit_cache: dict[str, list[Unit]],
) -> list[FlatLine]:
    ingredient = lines[0].ingredient
    buckets: list[_Bucket] = []

    for line in lines:
        placed = False
        for bucket in buckets:
            if bucket.add(line.quantity, line.unit):
                bucket.merge_provenance(line.from_recipes)
                placed = True
                break
        if not placed:
            bucket = _Bucket(ingredient, line.unit)
            bucket.add(line.quantity, line.unit)
            bucket.merge_provenance(line.from_recipes)
            buckets.append(bucket)

    result: list[FlatLine] = []
    for bucket in buckets:
        quantity, unit = _friendly_unit(bucket.total, bucket.unit, ingredient, unit_cache)
        result.append(
            FlatLine(
                ingredient=ingredient,
                quantity=quantity,
                unit=unit,
                from_recipes=tuple(bucket.from_recipes),
            )
        )
    return result


def _friendly_unit(
    quantity: Decimal,
    unit: Unit,
    ingredient: Ingredient,
    unit_cache: dict[str, list[Unit]],
) -> tuple[Decimal, Unit]:
    """Pick the unit that reads best for ``quantity``: keep the current unit while the number
    sits in [1, 1000), otherwise promote (1500 g → 1.5 kg) or demote (0.2 kg → 200 g).

    Promotion/demotion candidates are restricted to units on the **same power-of-ten ladder**
    as ``unit`` (g↔kg↔mg, ml↔l↔dl), so a metric total stays metric and an imperial one stays
    imperial — never "0.5 kg → 1.1 lb" or "0.3 l → 1.27 cup" (task 05 review finding 2). A unit
    with no ladder neighbour in range (most imperial units, every COUNT unit) simply keeps its
    own unit.
    """
    quantity = Decimal(quantity)
    if unit.dimension == Dimension.COUNT:
        return quantity, unit
    if _FRIENDLY_LOW <= quantity < _FRIENDLY_HIGH:
        return quantity, unit

    candidates: list[tuple[Unit, Decimal]] = []
    for candidate in _units_of_dimension(unit.dimension, unit_cache):
        if candidate.pk == unit.pk or not _on_decimal_ladder(unit, candidate):
            continue
        try:
            value = Decimal(convert(quantity, unit, candidate, ingredient))
        except IncompatibleUnits:
            continue
        if value > 0:
            candidates.append((candidate, value))

    in_range = [(c, v) for c, v in candidates if _FRIENDLY_LOW <= v < _FRIENDLY_HIGH]
    if in_range:
        # The largest in-range value is the most granular unit that still keeps the number
        # under 1000 — "300 ml", not "3 dl", for 0.3 litre.
        best_unit, best_value = max(in_range, key=lambda cv: (cv[1], cv[0].to_base_factor))
        return best_value, best_unit
    if not candidates:
        return quantity, unit
    if quantity >= _FRIENDLY_HIGH:
        best_unit, best_value = min(candidates, key=lambda cv: (cv[1], cv[0].to_base_factor))
    else:
        best_unit, best_value = max(candidates, key=lambda cv: (cv[1], cv[0].to_base_factor))
    return best_value, best_unit


def _on_decimal_ladder(source: Unit, candidate: Unit) -> bool:
    """True when ``candidate.to_base_factor`` is a power-of-ten multiple of
    ``source.to_base_factor`` — the two are the same measure at a different metric scale
    (gram/kilogram/milligram, millilitre/litre/decilitre). Any other ratio (gram→ounce,
    millilitre→cup) is a cross-system conversion ``_friendly_unit`` must not silently make.
    """
    try:
        ratio = (candidate.to_base_factor / source.to_base_factor).normalize()
    except ArithmeticError:
        return False
    _, digits, _ = ratio.as_tuple()
    return digits == (1,)


def _units_of_dimension(dimension: str, cache: dict[str, list[Unit]]) -> list[Unit]:
    units = cache.get(dimension)
    if units is None:
        units = list(Unit.objects.filter(dimension=dimension))
        cache[dimension] = units
    return units


__all__ = [
    "FlatLine",
    "FlattenError",
    "aggregate",
    "flatten",
    "scale",
]
