"""The bulk-JSON-import file format and its structural validation (task 09.9,
``Plan/09-Admin-Control-Center/design.md``, "Bulk JSON import").

This module knows the *shape* of an import file — the supported version, which sections exist,
which fields each object carries, and the denial-of-service caps (file size, object count,
nesting depth). It does no database work: whether a referenced unit, tag, ingredient or
sub-recipe actually resolves is ``core.services.importer``'s job, because that needs the
target owner and the visible-object set.

Every problem is reported as an :class:`ImportProblem` carrying a JSON-ish path
(``recipes[3].components[1].unit``) so an error against a 400-line file is actionable
(design.md, rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import DecimalValidator
from django.db.models import DecimalField

from recipes.models import Recipe, RecipeComponent, RecipeRole

#: Magnitude bounds for the two decimal quantities an import file carries, read straight off
#: the model fields so they cannot drift. Enforced during shape validation so a value wider
#: than the column (``Decimal("1E40")`` and the like) is a path-qualified problem rather than
#: an ``IntegrityError``/``DataError`` 500 from deep inside ``execute``.
_YIELD_QUANTITY_FIELD = Recipe._meta.get_field("yield_quantity")
_COMPONENT_QUANTITY_FIELD = RecipeComponent._meta.get_field("quantity")

#: Only version 1 exists. An unknown version is refused rather than guessed at — a future
#: format may move or rename fields, and a partial best-effort import is worse than none.
SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})

#: Denial-of-service caps (design.md, rule 4). File size and nesting depth are checked before
#: ``json.loads`` so a parser bomb never runs; the object count is checked on the parsed tree.
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_OBJECT_COUNT = 1000
MAX_NESTING_DEPTH = 10

SECTIONS: tuple[str, ...] = ("ingredients", "recipes", "dishes")


@dataclass(frozen=True)
class ImportProblem:
    """One reason an import file was rejected, located by a path into the file."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def max_json_depth(text: str) -> int:
    """The deepest nesting of ``{``/``[`` in ``text``, ignoring brackets inside strings.

    Scanned off the raw text rather than the parsed object so a maliciously deep file is
    rejected before ``json.loads`` builds (and recurses over) it.
    """
    depth = deepest = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "}]":
            depth -= 1
    return deepest


def count_objects(data: dict) -> int:
    """Every object the file asks to create: each ingredient, recipe and dish, plus every
    recipe component and every dish-recipe reference.
    """
    total = 0
    for section in SECTIONS:
        items = data.get(section)
        if not isinstance(items, list):
            continue
        total += len(items)
        for item in items:
            if not isinstance(item, dict):
                continue
            total += len(item.get("components", []) or []) if section == "recipes" else 0
            total += len(item.get("recipes", []) or []) if section == "dishes" else 0
    return total


def _decimal_or_problem(
    value: object, path: str, field: str, *, model_field: DecimalField | None = None
) -> Decimal | ImportProblem:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ImportProblem(f"{path}.{field}", f"{field} must be a number")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return ImportProblem(f"{path}.{field}", f"{field} is not a valid number: {value!r}")
    if not parsed.is_finite() or parsed <= 0:
        return ImportProblem(f"{path}.{field}", f"{field} must be greater than zero")
    if model_field is not None:
        try:
            DecimalValidator(model_field.max_digits, model_field.decimal_places)(parsed)
        except DjangoValidationError:
            return ImportProblem(
                f"{path}.{field}",
                f"{field} is out of range: at most {model_field.max_digits} digits, "
                f"{model_field.decimal_places} of them after the decimal point",
            )
    return parsed


def _require_str(item: dict, key: str, path: str, problems: list[ImportProblem]) -> None:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(ImportProblem(f"{path}.{key}", f"missing or empty required field {key!r}"))


def _optional_str_list(item: dict, key: str, path: str, problems: list[ImportProblem]) -> None:
    value = item.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(ImportProblem(f"{path}.{key}", f"{key!r} must be a list of strings"))


def _dupe_problems(items: list, section: str) -> list[ImportProblem]:
    """A name appearing twice in one section is ambiguous — every later reference could mean
    either object (design.md, "Edge cases").
    """
    seen: set[str] = set()
    problems: list[ImportProblem] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        key = name.strip().casefold()
        if key in seen:
            problems.append(
                ImportProblem(f"{section}[{index}].name", f"duplicate name {name!r} in {section}")
            )
        seen.add(key)
    return problems


def validate_shape(data: object) -> list[ImportProblem]:
    """Check ``data`` is a well-formed import file: right version, known sections, every
    object carrying its required fields with the right types. Returns an empty list when the
    shape is sound. Reference resolution and the cycle guard happen later, in the importer.
    """
    if not isinstance(data, dict):
        return [ImportProblem("", "the top level of the file must be a JSON object")]

    problems: list[ImportProblem] = []

    version = data.get("version")
    if version is None:
        problems.append(ImportProblem("version", "missing required field 'version'"))
    elif version not in SUPPORTED_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_VERSIONS))
        problems.append(
            ImportProblem("version", f"unsupported version {version!r} (supported: {supported})")
        )

    for section in SECTIONS:
        if section in data and not isinstance(data[section], list):
            problems.append(ImportProblem(section, f"{section!r} must be a list"))

    problems += _validate_ingredients(data.get("ingredients", []))
    problems += _validate_recipes(data.get("recipes", []))
    problems += _validate_dishes(data.get("dishes", []))
    return problems


def _validate_ingredients(items: object) -> list[ImportProblem]:
    if not isinstance(items, list):
        return []
    problems: list[ImportProblem] = []
    for index, item in enumerate(items):
        path = f"ingredients[{index}]"
        if not isinstance(item, dict):
            problems.append(ImportProblem(path, "each ingredient must be a JSON object"))
            continue
        _require_str(item, "name", path, problems)
        _require_str(item, "default_unit", path, problems)
        _optional_str_list(item, "tags", path, problems)
        if "is_staple" in item and not isinstance(item["is_staple"], bool):
            problems.append(ImportProblem(f"{path}.is_staple", "is_staple must be true or false"))
    problems += _dupe_problems(items, "ingredients")
    return problems


def _validate_recipes(items: object) -> list[ImportProblem]:
    if not isinstance(items, list):
        return []
    problems: list[ImportProblem] = []
    for index, item in enumerate(items):
        path = f"recipes[{index}]"
        if not isinstance(item, dict):
            problems.append(ImportProblem(path, "each recipe must be a JSON object"))
            continue
        _require_str(item, "name", path, problems)
        _require_str(item, "yield_unit", path, problems)
        result = _decimal_or_problem(
            item.get("yield_quantity"), path, "yield_quantity", model_field=_YIELD_QUANTITY_FIELD
        )
        if isinstance(result, ImportProblem):
            problems.append(result)
        role = item.get("role")
        if role is not None and role not in RecipeRole.values:
            problems.append(ImportProblem(f"{path}.role", f"unknown role {role!r}"))
        for field in ("prep_minutes", "cook_minutes"):
            if field in item and (
                isinstance(item[field], bool) or not isinstance(item[field], int) or item[field] < 0
            ):
                problems.append(
                    ImportProblem(f"{path}.{field}", f"{field} must be a non-negative integer")
                )
        _optional_str_list(item, "tags", path, problems)
        problems += _validate_components(item.get("components", []), path)
    problems += _dupe_problems(items, "recipes")
    return problems


def _validate_components(components: object, recipe_path: str) -> list[ImportProblem]:
    if not isinstance(components, list):
        return [ImportProblem(f"{recipe_path}.components", "'components' must be a list")]
    problems: list[ImportProblem] = []
    for index, comp in enumerate(components):
        path = f"{recipe_path}.components[{index}]"
        if not isinstance(comp, dict):
            problems.append(ImportProblem(path, "each component must be a JSON object"))
            continue
        has_ingredient = isinstance(comp.get("ingredient"), str) and comp["ingredient"].strip()
        has_sub_recipe = isinstance(comp.get("sub_recipe"), str) and comp["sub_recipe"].strip()
        if bool(has_ingredient) == bool(has_sub_recipe):
            problems.append(
                ImportProblem(
                    path, "a component must name exactly one of 'ingredient' or 'sub_recipe'"
                )
            )
        _require_str(comp, "unit", path, problems)
        result = _decimal_or_problem(
            comp.get("quantity"), path, "quantity", model_field=_COMPONENT_QUANTITY_FIELD
        )
        if isinstance(result, ImportProblem):
            problems.append(result)
    return problems


def _validate_dishes(items: object) -> list[ImportProblem]:
    if not isinstance(items, list):
        return []
    problems: list[ImportProblem] = []
    for index, item in enumerate(items):
        path = f"dishes[{index}]"
        if not isinstance(item, dict):
            problems.append(ImportProblem(path, "each dish must be a JSON object"))
            continue
        _require_str(item, "name", path, problems)
        _optional_str_list(item, "tags", path, problems)
        recipes = item.get("recipes", [])
        if not isinstance(recipes, list) or not all(isinstance(r, str) for r in recipes):
            problems.append(
                ImportProblem(f"{path}.recipes", "'recipes' must be a list of recipe names")
            )
    problems += _dupe_problems(items, "dishes")
    return problems
