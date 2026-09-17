"""Bulk JSON import — validate the whole file, then apply it in one atomic transaction
(task 09.9 / 09.10, ``Plan/09-Admin-Control-Center/design.md``, "Bulk JSON import").

The two halves, deliberately separate:

* :func:`validate` — a complete dry run. Parses, enforces the denial-of-service caps, checks
  every object's shape (:mod:`core.schemas`), then resolves every reference (units, tags,
  ingredients, sub-recipes) against the in-file objects and the target owner's *visible* set.
  It writes nothing and returns an :class:`ImportPlan`, or raises
  :class:`ImportValidationError` carrying a path-qualified problem for every fault at once.
* :func:`execute` — applies a validated :class:`ImportPlan`. Two passes so a recipe may
  reference a sub-recipe defined later in the file; one ``transaction.atomic()`` so a fault
  part-way through leaves nothing behind; the recipe cycle guard runs on every imported
  sub-recipe edge. A successful (non-dry) run writes one audit ``LogEntry`` with the
  per-section object counts, inside the same transaction (09.13).

:func:`run_import` chains the two and is what both entry points — the admin upload page and
``manage.py import_json`` — call, so the two paths cannot drift.

**Security invariants** (design.md, "Security notes"):

* ``owner`` is the argument, never a value read from the file. A payload key called ``owner``
  or ``is_system`` is ignored outright — it would be privilege escalation and attribution
  forgery.
* References resolve only against objects the owner can already see
  (``.visible_to(owner)``) — naming another user's private ingredient does not bind to it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from catalog.exceptions import IncompatibleUnits
from catalog.models import Ingredient, Tag, Unit
from catalog.services.units import convert
from core.schemas import (
    MAX_FILE_BYTES,
    MAX_NESTING_DEPTH,
    MAX_OBJECT_COUNT,
    ImportProblem,
    count_objects,
    max_json_depth,
    validate_shape,
)
from meals.models import Dish, DishComponent
from recipes.models import Recipe, RecipeComponent, RecipeRole
from recipes.services.graph import GraphError, assert_no_cycle

SKIP_EXISTING = "skip-existing"
UPDATE_EXISTING = "update-existing"
MODES = (SKIP_EXISTING, UPDATE_EXISTING)


class ImportValidationError(Exception):
    """The file was rejected. ``problems`` lists every fault found, each with a path."""

    def __init__(self, problems: list[ImportProblem]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(p) for p in problems) or "invalid import file")


@dataclass(frozen=True)
class _ComponentSpec:
    ingredient_name: str | None
    sub_recipe_name: str | None
    quantity: Decimal
    unit: Unit
    note: str


@dataclass(frozen=True)
class _IngredientSpec:
    name: str
    default_unit: Unit
    tags: tuple[Tag, ...]
    is_staple: bool
    notes: str


@dataclass(frozen=True)
class _RecipeSpec:
    name: str
    yield_quantity: Decimal
    yield_unit: Unit
    instructions: str
    description: str
    role: str
    prep_minutes: int
    cook_minutes: int
    tags: tuple[Tag, ...]
    components: tuple[_ComponentSpec, ...]


@dataclass(frozen=True)
class _DishSpec:
    name: str
    description: str
    tags: tuple[Tag, ...]
    recipe_names: tuple[str, ...]


@dataclass(frozen=True)
class ImportPlan:
    """A validated import, ready for :func:`execute`."""

    ingredients: tuple[_IngredientSpec, ...]
    recipes: tuple[_RecipeSpec, ...]
    dishes: tuple[_DishSpec, ...]


@dataclass
class ImportReport:
    """What an :func:`execute` run did (or, on a dry run, would have done)."""

    created: dict[str, int] = field(default_factory=lambda: {s: 0 for s in _SECTIONS})
    updated: dict[str, int] = field(default_factory=lambda: {s: 0 for s in _SECTIONS})
    skipped: dict[str, int] = field(default_factory=lambda: {s: 0 for s in _SECTIONS})
    dry_run: bool = False

    def as_lines(self) -> list[str]:
        verb = "would create" if self.dry_run else "created"
        lines = []
        for section in _SECTIONS:
            lines.append(
                f"{section}: {verb} {self.created[section]}, "
                f"updated {self.updated[section]}, skipped {self.skipped[section]}"
            )
        return lines


_SECTIONS = ("ingredients", "recipes", "dishes")


# --- validation -----------------------------------------------------------------------------


def _as_text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImportValidationError(
                [ImportProblem("", f"file is not valid UTF-8 text: {exc}")]
            ) from exc
    return raw


def validate(raw: bytes | str, *, owner) -> ImportPlan:
    """Full dry-run validation. Returns an :class:`ImportPlan` or raises
    :class:`ImportValidationError` with a problem per fault. Writes nothing.
    """
    text = _as_text(raw)

    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportValidationError(
            [ImportProblem("", f"file is larger than the {MAX_FILE_BYTES // (1024 * 1024)} MB cap")]
        )

    depth = max_json_depth(text)
    if depth > MAX_NESTING_DEPTH:
        raise ImportValidationError(
            [ImportProblem("", f"file nests {depth} levels deep; the cap is {MAX_NESTING_DEPTH}")]
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        where = f"line {exc.lineno}, column {exc.colno}"
        raise ImportValidationError(
            [ImportProblem("", f"malformed JSON at {where}: {exc.msg}")]
        ) from exc

    # Shape-checking iterates every object before ``count_objects`` enforces MAX_OBJECT_COUNT.
    # Deliberate: the work is O(file size) and the 5 MB byte cap checked above already bounds
    # it, and ``validate_shape`` is also what rejects a non-dict top level with a clean
    # path-qualified problem — running the object-count cap first would need that guard
    # duplicated here.
    shape_problems = validate_shape(data)
    if shape_problems:
        raise ImportValidationError(shape_problems)

    total = count_objects(data)
    if total > MAX_OBJECT_COUNT:
        raise ImportValidationError(
            [ImportProblem("", f"file describes {total} objects; the cap is {MAX_OBJECT_COUNT}")]
        )

    resolver = _Resolver(owner)
    plan = resolver.build_plan(data)
    if resolver.problems:
        raise ImportValidationError(resolver.problems)
    return plan


class _Resolver:
    """Turns the shape-valid raw ``data`` into an :class:`ImportPlan`, accumulating a problem
    for every reference that does not resolve.
    """

    def __init__(self, owner) -> None:
        self.owner = owner
        self.problems: list[ImportProblem] = []

        self._units: dict[str, Unit] = {}
        for unit in Unit.objects.all():
            self._units.setdefault(unit.abbrev.casefold(), unit)
            self._units[unit.name.casefold()] = unit
        self._tags: dict[str, Tag] = {t.name.casefold(): t for t in Tag.objects.all()}

        self._visible_ingredients: set[str] = {
            name.casefold()
            for name in Ingredient.objects.visible_to(owner).values_list("name", flat=True)
        }
        self._visible_recipes: set[str] = set()
        #: Every recipe a component may name as a sub-recipe (visible rows now, in-file recipes
        #: added in ``build_plan``) mapped to its yield unit — needed to check, at validation
        #: time, that a sub-recipe component's unit can actually be scaled to that yield.
        self._recipe_yield_units: dict[str, Unit] = {}
        for recipe in Recipe.objects.visible_to(owner).select_related("yield_unit"):
            key = recipe.name.casefold()
            self._visible_recipes.add(key)
            self._recipe_yield_units[key] = recipe.yield_unit
        self._in_file_ingredients: set[str] = set()
        self._in_file_recipes: set[str] = set()

    def build_plan(self, data: dict) -> ImportPlan:
        self._in_file_ingredients = {
            i["name"].strip().casefold() for i in data.get("ingredients", []) if i.get("name")
        }
        self._in_file_recipes = {
            r["name"].strip().casefold() for r in data.get("recipes", []) if r.get("name")
        }
        for item in data.get("recipes", []):
            name = item.get("name")
            token = item.get("yield_unit")
            if isinstance(name, str) and isinstance(token, str):
                unit = self._units.get(token.strip().casefold())
                if unit is not None:
                    self._recipe_yield_units[name.strip().casefold()] = unit

        ingredients = tuple(
            self._ingredient_spec(item, f"ingredients[{i}]")
            for i, item in enumerate(data.get("ingredients", []))
        )
        recipes = tuple(
            self._recipe_spec(item, f"recipes[{i}]")
            for i, item in enumerate(data.get("recipes", []))
        )
        dishes = tuple(
            self._dish_spec(item, f"dishes[{i}]") for i, item in enumerate(data.get("dishes", []))
        )
        self._check_in_file_cycles(data.get("recipes", []))
        return ImportPlan(
            ingredients=tuple(s for s in ingredients if s is not None),
            recipes=tuple(s for s in recipes if s is not None),
            dishes=dishes,
        )

    def _unit(self, token: str, path: str) -> Unit | None:
        unit = self._units.get(token.strip().casefold())
        if unit is None:
            self.problems.append(ImportProblem(path, f"unknown unit {token!r}"))
        return unit

    def _tag_list(self, item: dict, path: str) -> tuple[Tag, ...]:
        resolved: list[Tag] = []
        for index, name in enumerate(item.get("tags", []) or []):
            tag = self._tags.get(name.strip().casefold())
            if tag is None:
                self.problems.append(
                    ImportProblem(f"{path}.tags[{index}]", f"unknown tag {name!r}")
                )
            else:
                resolved.append(tag)
        return tuple(resolved)

    def _ingredient_spec(self, item: dict, path: str) -> _IngredientSpec | None:
        unit = self._unit(item["default_unit"], f"{path}.default_unit")
        tags = self._tag_list(item, path)
        if unit is None:
            return None
        return _IngredientSpec(
            name=item["name"].strip(),
            default_unit=unit,
            tags=tags,
            is_staple=bool(item.get("is_staple", False)),
            notes=str(item.get("notes", "") or ""),
        )

    def _recipe_spec(self, item: dict, path: str) -> _RecipeSpec | None:
        yield_unit = self._unit(item["yield_unit"], f"{path}.yield_unit")
        tags = self._tag_list(item, path)
        components = tuple(
            spec
            for index, comp in enumerate(item.get("components", []))
            if (spec := self._component_spec(comp, f"{path}.components[{index}]"))
        )
        if yield_unit is None:
            return None
        return _RecipeSpec(
            name=item["name"].strip(),
            yield_quantity=Decimal(str(item["yield_quantity"])),
            yield_unit=yield_unit,
            instructions=str(item.get("instructions", "") or ""),
            description=str(item.get("description", "") or ""),
            role=item.get("role") or RecipeRole.OTHER,
            prep_minutes=int(item.get("prep_minutes", 0) or 0),
            cook_minutes=int(item.get("cook_minutes", 0) or 0),
            tags=tags,
            components=components,
        )

    def _component_spec(self, comp: dict, path: str) -> _ComponentSpec | None:
        unit = self._unit(comp["unit"], f"{path}.unit")
        ingredient_name = (comp.get("ingredient") or "").strip() or None
        sub_recipe_name = (comp.get("sub_recipe") or "").strip() or None

        if ingredient_name is not None and not self._ingredient_known(ingredient_name):
            self.problems.append(
                ImportProblem(f"{path}.ingredient", f"unknown ingredient {ingredient_name!r}")
            )
            return None
        if sub_recipe_name is not None and not self._recipe_known(sub_recipe_name):
            self.problems.append(
                ImportProblem(f"{path}.sub_recipe", f"unknown sub-recipe {sub_recipe_name!r}")
            )
            return None
        if unit is None:
            return None
        quantity = Decimal(str(comp["quantity"]))
        if sub_recipe_name is not None and not self._sub_recipe_unit_scalable(
            sub_recipe_name, quantity, unit, f"{path}.unit"
        ):
            return None
        return _ComponentSpec(
            ingredient_name=ingredient_name,
            sub_recipe_name=sub_recipe_name,
            quantity=quantity,
            unit=unit,
            note=str(comp.get("note", "") or ""),
        )

    def _sub_recipe_unit_scalable(
        self, sub_recipe_name: str, quantity: Decimal, unit: Unit, path: str
    ) -> bool:
        """A sub-recipe component's quantity is scaled by ``convert(quantity, unit,
        sub_recipe.yield_unit)`` when the recipe is flattened. If that conversion is impossible
        — the two units measure different things — the recipe can never become a shopping
        list, so the file is refused here at validation rather than committing a row that only
        blows up later in the flattener. This is the same guard the REST
        (``recipes/serializers.py``) and HTML (``recipes/services/components.py``) write paths
        enforce (CLAUDE.md §6: never implement the same rule twice).
        """
        yield_unit = self._recipe_yield_units.get(sub_recipe_name.strip().casefold())
        if yield_unit is None:
            return True
        try:
            convert(quantity, unit, yield_unit)
        except IncompatibleUnits:
            self.problems.append(
                ImportProblem(
                    path,
                    f"cannot scale sub-recipe {sub_recipe_name!r}: it is called for in "
                    f"{unit.name} but yields {yield_unit.name}, and those measure different "
                    "things",
                )
            )
            return False
        return True

    def _dish_spec(self, item: dict, path: str) -> _DishSpec:
        recipe_names: list[str] = []
        for index, name in enumerate(item.get("recipes", []) or []):
            clean = name.strip()
            if self._recipe_known(clean):
                recipe_names.append(clean)
            else:
                self.problems.append(
                    ImportProblem(f"{path}.recipes[{index}]", f"unknown recipe {name!r}")
                )
        return _DishSpec(
            name=item["name"].strip(),
            description=str(item.get("description", "") or ""),
            tags=self._tag_list(item, path),
            recipe_names=tuple(recipe_names),
        )

    def _ingredient_known(self, name: str) -> bool:
        key = name.strip().casefold()
        return key in self._in_file_ingredients or key in self._visible_ingredients

    def _recipe_known(self, name: str) -> bool:
        key = name.strip().casefold()
        return key in self._in_file_recipes or key in self._visible_recipes

    def _check_in_file_cycles(self, raw_recipes: list) -> None:
        """A recipe referencing itself through in-file sub-recipes, before the DB even sees it."""
        graph: dict[str, set[str]] = {}
        for item in raw_recipes:
            name = item.get("name", "").strip().casefold()
            edges = {
                (c.get("sub_recipe") or "").strip().casefold()
                for c in item.get("components", [])
                if c.get("sub_recipe")
            }
            graph[name] = {e for e in edges if e}

        visiting: set[str] = set()
        done: set[str] = set()

        def walk(node: str, trail: list[str]) -> None:
            if node in done or node not in graph:
                return
            if node in visiting:
                cycle = " → ".join([*trail, node])
                self.problems.append(
                    ImportProblem("recipes", f"sub-recipe cycle within the file: {cycle}")
                )
                return
            visiting.add(node)
            for nxt in graph[node]:
                walk(nxt, [*trail, node])
            visiting.discard(node)
            done.add(node)

        for name in list(graph):
            walk(name, [])


# --- execution ------------------------------------------------------------------------------


def execute(
    plan: ImportPlan,
    *,
    owner,
    actor=None,
    mode: str = SKIP_EXISTING,
    dry_run: bool = False,
) -> ImportReport:
    """Apply a validated ``plan`` as ``owner``, in one transaction. ``mode`` decides what
    happens to an existing ``(owner, name)`` match — skip it, or overwrite its fields and
    components. ``dry_run`` rolls the whole transaction back and reports what would have run.
    """
    if mode not in MODES:
        raise ValueError(f"unknown import mode {mode!r}")

    from core.services import audit

    report = ImportReport(dry_run=dry_run)
    with transaction.atomic():
        ingredients = _apply_ingredients(plan, owner, mode, report)
        recipes = _apply_recipe_shells(plan, owner, mode, report)
        _apply_recipe_components(plan, owner, mode, ingredients, recipes)
        _apply_dishes(plan, owner, mode, recipes, report)
        if dry_run:
            transaction.set_rollback(True)
        else:
            # Inside the transaction so the audit record and the import commit or roll back
            # together — a real run always leaves a trail, a dry run leaves nothing.
            audit.record_import_run(actor=actor, owner=owner, report=report, mode=mode)
    return report


def _apply_ingredients(plan, owner, mode, report) -> dict[str, Ingredient]:
    resolved: dict[str, Ingredient] = {}
    for spec in plan.ingredients:
        existing = Ingredient.objects.filter(owner=owner, name__iexact=spec.name).first()
        if existing is not None:
            if mode == UPDATE_EXISTING:
                existing.default_unit = spec.default_unit
                existing.is_staple = spec.is_staple
                existing.notes = spec.notes
                existing.save(update_fields=["default_unit", "is_staple", "notes"])
                existing.tags.set(spec.tags)
                report.updated["ingredients"] += 1
            else:
                report.skipped["ingredients"] += 1
            resolved[spec.name.casefold()] = existing
            continue
        obj = Ingredient.objects.create(
            owner=owner,
            name=spec.name,
            default_unit=spec.default_unit,
            is_staple=spec.is_staple,
            notes=spec.notes,
        )
        obj.tags.set(spec.tags)
        report.created["ingredients"] += 1
        resolved[spec.name.casefold()] = obj
    return resolved


def _apply_recipe_shells(plan, owner, mode, report) -> dict[str, tuple[Recipe, bool]]:
    """First pass: every recipe exists as a row (no components yet) so pass two can wire
    forward references. The bool is "populate its components" — false for a skipped match.
    """
    resolved: dict[str, tuple[Recipe, bool]] = {}
    for spec in plan.recipes:
        existing = Recipe.objects.filter(owner=owner, name__iexact=spec.name).first()
        if existing is not None:
            if mode == UPDATE_EXISTING:
                existing.yield_quantity = spec.yield_quantity
                existing.yield_unit = spec.yield_unit
                existing.instructions = spec.instructions
                existing.description = spec.description
                existing.role = spec.role
                existing.prep_minutes = spec.prep_minutes
                existing.cook_minutes = spec.cook_minutes
                existing.save()
                existing.tags.set(spec.tags)
                report.updated["recipes"] += 1
                resolved[spec.name.casefold()] = (existing, True)
            else:
                report.skipped["recipes"] += 1
                resolved[spec.name.casefold()] = (existing, False)
            continue
        obj = Recipe.objects.create(
            owner=owner,
            name=spec.name,
            yield_quantity=spec.yield_quantity,
            yield_unit=spec.yield_unit,
            instructions=spec.instructions,
            description=spec.description,
            role=spec.role,
            prep_minutes=spec.prep_minutes,
            cook_minutes=spec.cook_minutes,
        )
        obj.tags.set(spec.tags)
        report.created["recipes"] += 1
        resolved[spec.name.casefold()] = (obj, True)
    return resolved


def _resolve_ingredient(name: str, owner, in_file: dict[str, Ingredient]) -> Ingredient | None:
    in_file_match = in_file.get(name.casefold())
    if in_file_match is not None:
        return in_file_match
    # Bind the owner's *own* object first; only fall back to the wider visible set (public or
    # shared rows owned by someone else) when the owner has nothing by that name. Without the
    # owner-first ordering, a name that matches both binds nondeterministically.
    candidates = Ingredient.objects.visible_to(owner).filter(name__iexact=name)
    return candidates.filter(owner=owner).first() or candidates.first()


def _resolve_recipe(name: str, owner, in_file: dict[str, tuple[Recipe, bool]]) -> Recipe | None:
    match = in_file.get(name.casefold())
    if match is not None:
        return match[0]
    candidates = Recipe.objects.visible_to(owner).filter(name__iexact=name)
    return candidates.filter(owner=owner).first() or candidates.first()


def _apply_recipe_components(plan, owner, mode, ingredients, recipes) -> None:
    for spec in plan.recipes:
        recipe, populate = recipes[spec.name.casefold()]
        if not populate:
            continue
        if mode == UPDATE_EXISTING:
            recipe.components.all().delete()
        for position, comp in enumerate(spec.components):
            ingredient = sub_recipe = None
            if comp.ingredient_name is not None:
                ingredient = _resolve_ingredient(comp.ingredient_name, owner, ingredients)
                if ingredient is None:
                    raise ImportValidationError(
                        [ImportProblem(spec.name, f"ingredient {comp.ingredient_name!r} vanished")]
                    )
            else:
                sub_recipe = _resolve_recipe(comp.sub_recipe_name, owner, recipes)
                if sub_recipe is None:
                    raise ImportValidationError(
                        [ImportProblem(spec.name, f"sub-recipe {comp.sub_recipe_name!r} vanished")]
                    )
                try:
                    assert_no_cycle(recipe, sub_recipe)
                except GraphError as exc:
                    raise ImportValidationError(
                        [ImportProblem(f"{spec.name}.components[{position}]", str(exc))]
                    ) from exc
            RecipeComponent.objects.create(
                recipe=recipe,
                ingredient=ingredient,
                sub_recipe=sub_recipe,
                quantity=comp.quantity,
                unit=comp.unit,
                position=position,
                note=comp.note,
            )


def _apply_dishes(plan, owner, mode, recipes, report) -> None:
    for spec in plan.dishes:
        existing = Dish.objects.filter(owner=owner, name__iexact=spec.name).first()
        if existing is not None and mode == SKIP_EXISTING:
            report.skipped["dishes"] += 1
            continue
        if existing is not None:
            existing.description = spec.description
            existing.save(update_fields=["description"])
            existing.tags.set(spec.tags)
            existing.components.all().delete()
            dish = existing
            report.updated["dishes"] += 1
        else:
            dish = Dish.objects.create(owner=owner, name=spec.name, description=spec.description)
            dish.tags.set(spec.tags)
            report.created["dishes"] += 1
        for position, name in enumerate(spec.recipe_names):
            recipe = _resolve_recipe(name, owner, recipes)
            if recipe is None:
                raise ImportValidationError([ImportProblem(spec.name, f"recipe {name!r} vanished")])
            DishComponent.objects.create(
                dish=dish, recipe=recipe, servings=Decimal("1"), position=position
            )


# --- the combined entry point --------------------------------------------------------------


def run_import(
    *,
    raw: bytes | str,
    owner,
    actor=None,
    mode: str = SKIP_EXISTING,
    dry_run: bool = False,
) -> ImportReport:
    """Validate ``raw`` and, if it is sound, apply it as ``owner``. Both the admin upload
    page and ``manage.py import_json`` call this, so the two paths produce identical results.

    ``owner`` is authoritative: no ``owner`` / ``is_system`` value in the file is ever read.
    """
    plan = validate(raw, owner=owner)
    return execute(plan, owner=owner, actor=actor, mode=mode, dry_run=dry_run)
