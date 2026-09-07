"""List and shopping-list business logic (``Plan/07-Lists-And-Shopping/design.md``, "Services").

Everything the REST API and (from 07.9) the HTMX UI both need lives here, never in a view or a
serializer — the two surfaces share this layer so a rule is written once (``ARCHITECTURE.md``,
section 6).

``populate_shopping_list`` is the contract task 08 calls. Its whole reason to exist is C8:
regenerating a meal plan must replace only the lines *that plan* produced, leaving every
hand-typed line and every other plan's lines untouched (design.md, "``source`` and
``generated_from``").

**Provenance.** A ``GENERATED`` line records its contributing *dish* on ``ListItem.dish`` — but
only when exactly one dish contributed to that aggregated ingredient line. When several dishes
share an ingredient the line is genuinely "from the meal plan", so ``dish`` is left null and
``generated_from`` carries the provenance. The full root→leaf recipe chain that
``recipes.services.flatten.FlatLine.from_recipes`` carries is deliberately *not* persisted:
at the shopping-list layer the useful "why is this on my list" is "which dinner", not the
sub-recipe nesting path (07.5 provenance note).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Max, PositiveIntegerField, Q, Value, When

from catalog.exceptions import IncompatibleUnits
from catalog.models import Unit
from catalog.services.units import convert
from lists.models import ItemSource, List, ListItem, ListKind
from meals.models import Dish
from meals.services.dishes import flatten_dish
from recipes.models import Recipe
from recipes.services.flatten import FlatLine, aggregate
from recipes.services.flatten import flatten as flatten_recipe

_DEFAULT_SHOPPING_LIST_NAME = "Shopping List"

#: ``ListItem.quantity`` is ``max_digits=10, decimal_places=3`` — the largest value that fits
#: once quantised to 3 places. ``update_item`` range-checks against this so a fat-fingered
#: number is a clean 400 / error message, not a 500 from Django's decimal DB-prep.
_QUANTITY_DECIMAL_PLACES = 3
_QUANTITY_MAX = Decimal("9999999.999")


class ListError(Exception):
    """A list operation was refused for a reason the caller can act on — an unknown item id in
    a reorder, a dish that is not theirs to expand.
    """


class ListVisibilityError(ListError):
    """A referenced dish / recipe / ingredient is not visible to the actor. Attaching a guessed
    id to your own list and reading it back is the attack this closes (design.md, "Security
    notes"); the API maps it to a 400, the same as a nonexistent id.
    """


@dataclass(frozen=True)
class ShoppingResult:
    """What ``populate_shopping_list`` did, so the UI can say so instead of silently mutating a
    list (design.md, "``populate_shopping_list`` ... Returns a summary").
    """

    added: int
    replaced: int
    staples_skipped: int
    items: list[ListItem] = field(default_factory=list)


# --- default shopping list --------------------------------------------------------------------


def get_or_create_default_shopping_list(user: object) -> List:
    """The user's designated shopping list, created (named "Shopping List", kind ``SHOPPING``,
    flag set) if they have none yet.

    Race-safe: the ``lists_list_one_default_shopping_per_owner`` partial unique constraint is
    the arbiter, and a losing concurrent creator catches the ``IntegrityError`` and re-reads
    rather than returning a second list (design.md, "The default shopping list").
    """
    existing = List.objects.filter(owner=user, is_default_shopping_list=True).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            return List.objects.create(
                owner=user,
                name=_DEFAULT_SHOPPING_LIST_NAME,
                kind=ListKind.SHOPPING,
                is_default_shopping_list=True,
            )
    except IntegrityError:
        return List.objects.get(owner=user, is_default_shopping_list=True)


# --- adding recipes and dishes ---------------------------------------------------------------


def next_position(lst: List) -> int:
    """The position one past the current last item — where a freshly appended item goes."""
    current_max = lst.items.aggregate(highest=Max("position"))["highest"]
    return 0 if current_max is None else current_max + 1


def add_recipe_to_list(lst: List, recipe: Recipe, *, actor: object) -> list[ListItem]:
    """Append ``recipe`` to ``lst`` as a **single reference line** — never its ingredients, on
    any kind of list. Expanding a recipe to ingredients is a *dish*-on-a-shopping-list
    behaviour; a recipe on a list is "make this" (test-plan: "the distinction is easy to get
    backwards").
    """
    if not Recipe.objects.visible_to(actor).filter(pk=recipe.pk).exists():
        raise ListVisibilityError("That recipe is not available to you.")
    item = ListItem.objects.create(
        list=lst,
        position=next_position(lst),
        recipe=recipe,
        source=ItemSource.MANUAL,
    )
    return [item]


def add_dish_to_list(
    lst: List, dish: Dish, *, actor: object, exclude_staples: bool = True
) -> list[ListItem]:
    """Add ``dish`` to ``lst``.

    On a ``SHOPPING`` list the dish is **expanded** to its flattened, aggregated ingredient
    lines, merged into any existing generated lines for the same ingredient+unit so adding the
    same dish twice does not duplicate every line (design.md, "Edge cases"). On every other
    kind of list the dish is a single reference line.
    """
    visible = Dish.objects.with_component_graph().visible_to(actor).filter(pk=dish.pk).first()
    if visible is None:
        raise ListVisibilityError("That dish is not available to you.")

    if lst.kind != ListKind.SHOPPING:
        item = ListItem.objects.create(
            list=lst,
            position=next_position(lst),
            dish=visible,
            source=ItemSource.MANUAL,
        )
        return [item]

    lines = flatten_dish(visible, exclude_staples=exclude_staples, viewer=actor)
    with transaction.atomic():
        return _merge_generated_lines(lst, lines, source_plan=None, provenance_dish=visible)


def _merge_generated_lines(
    lst: List,
    lines: Iterable[FlatLine],
    *,
    source_plan: object | None,
    provenance_dish: Dish | None,
) -> list[ListItem]:
    """Upsert ``lines`` as ``GENERATED`` items on ``lst``: an existing generated line for the
    same ``(ingredient, unit)`` and ``source_plan`` gets its quantity increased, anything new
    is created. Caller wraps this in a transaction.
    """
    existing = {
        (item.ingredient_id, item.unit_id): item
        for item in lst.items.filter(
            source=ItemSource.GENERATED,
            generated_from=source_plan,
            ingredient__isnull=False,
        )
    }
    position = next_position(lst)
    created: list[ListItem] = []
    touched: list[ListItem] = []
    for line in lines:
        key = (line.ingredient.pk, line.unit.pk)
        item = existing.get(key)
        if item is not None:
            item.quantity = (item.quantity or Decimal(0)) + line.quantity
            update_fields = ["quantity"]
            # Provenance follows the same "null when more than one contributes" rule as
            # ``populate_shopping_list``: once a second, different dish merges into a line, "from
            # A" is no longer the whole truth (07.1 review, finding 5).
            if (
                provenance_dish is not None
                and item.dish_id is not None
                and item.dish_id != provenance_dish.pk
            ):
                item.dish = None
                update_fields.append("dish")
            item.save(update_fields=update_fields)
            touched.append(item)
            continue
        new_item = ListItem(
            list=lst,
            position=position,
            ingredient=line.ingredient,
            quantity=line.quantity,
            unit=line.unit,
            source=ItemSource.GENERATED,
            generated_from=source_plan,
            dish=provenance_dish,
        )
        existing[key] = new_item
        created.append(new_item)
        position += 1
    if created:
        ListItem.objects.bulk_create(created)
    return [*created, *touched]


# --- meal-plan population (the task 08 contract) --------------------------------------------


def populate_shopping_list(
    lst: List,
    dishes: Sequence[Dish],
    *,
    source_plan: object | None = None,
    exclude_staples: bool = True,
    replace_generated: bool = True,
) -> ShoppingResult:
    """Flatten every dish, aggregate across all of them (one line per ingredient for the whole
    week), and write the result to ``lst`` as ``GENERATED`` items.

    - Visibility is checked first: every dish must be visible to ``lst.owner`` or the whole
      call raises ``ListVisibilityError`` before anything is written (design.md, "Security
      notes").
    - When ``replace_generated`` (the default), existing ``GENERATED`` items **belonging to
      ``source_plan``** are deleted first — scoping the delete to the plan is what lets two
      plans feed one list without trampling each other (C8).
    - ``MANUAL`` items are never touched. Neither are another plan's ``GENERATED`` items.
    - The checked state of a replaced generated item is lost — accepted and documented
      (design.md, "Edge cases"); the UI warns before regenerating a list with checked items.
    - The whole thing is one transaction: a mid-way failure leaves ``lst`` exactly as it was.
    """
    computed = _flatten_dishes_to_lines(lst.owner, dishes, exclude_staples=exclude_staples)

    with transaction.atomic():
        replaced = 0
        if replace_generated:
            replaced, _ = lst.items.filter(
                source=ItemSource.GENERATED, generated_from=source_plan
            ).delete()

        position = next_position(lst)
        new_items: list[ListItem] = []
        for offset, line in enumerate(computed.kept):
            sources = computed.contributors.get(line.ingredient.pk, set())
            provenance_dish = (
                computed.dish_by_id[next(iter(sources))] if len(sources) == 1 else None
            )
            new_items.append(
                ListItem(
                    list=lst,
                    position=position + offset,
                    ingredient=line.ingredient,
                    quantity=line.quantity,
                    unit=line.unit,
                    source=ItemSource.GENERATED,
                    generated_from=source_plan,
                    dish=provenance_dish,
                )
            )
        if new_items:
            ListItem.objects.bulk_create(new_items)

    return ShoppingResult(
        added=len(new_items),
        replaced=replaced,
        staples_skipped=computed.staples_skipped,
        items=new_items,
    )


@dataclass(frozen=True)
class _ShoppingLines:
    kept: list[FlatLine]
    contributors: dict[int, set[int]]
    dish_by_id: dict[int, Dish]
    staples_skipped: int


def _flatten_dishes_to_lines(
    actor: object, dishes: Sequence[Dish], *, exclude_staples: bool
) -> _ShoppingLines:
    """Flatten every dish, aggregate across all of them (one line per ingredient for the whole
    week), drop staples if asked. Pure — reads only, writes nothing.

    Shared by ``populate_shopping_list`` and ``preview_shopping_list`` so the meal planner's
    on-screen preview and the list it eventually writes can never disagree. Raises
    ``ListVisibilityError`` if any dish is not visible to ``actor``, before returning anything.
    """
    requested = list(dishes)
    requested_ids = {dish.pk for dish in requested}

    visible = {
        dish.pk: dish
        for dish in (
            Dish.objects.visible_to(actor)
            .filter(pk__in=requested_ids)
            .prefetch_related("components")
        )
    }
    if len(visible) != len(requested_ids):
        raise ListVisibilityError(
            "One of the dishes in this plan is not available to you, so the shopping list "
            "cannot be built."
        )

    # A dish scheduled twice in a plan (repeated dinner, hand-picked plan, short
    # ``no_repeat_days``) must double the groceries it needs — ``aggregate()`` below sums the
    # repeated components naturally. No dish-level dedupe: ``add_dish_to_list`` twice already
    # yields 2x, and a short shopping line is the exact failure this task exists to prevent
    # (07.1 review, finding 2).
    components = [
        (dish.pk, component)
        for dish in requested
        for component in visible[dish.pk].components.all()
    ]
    # Every component recipe's whole sub-recipe / ingredient graph, prefetched in one bounded
    # batch — so ``flatten_recipe`` below reuses it rather than re-fetching per component (the
    # N+1 ``test_populate_query_count`` guards against). ``actor`` is not re-consulted here:
    # every dish is already confirmed visible to it above, and this is the trusted "walking its
    # owner's own dishes" path (``meals.services.dishes.flatten_dish``).
    recipe_ids = {component.recipe_id for _, component in components}
    graph_recipes = {
        recipe.pk: recipe
        for recipe in Recipe.objects.with_component_graph().filter(pk__in=recipe_ids)
    }

    contributors: dict[int, set[int]] = {}
    all_lines: list[FlatLine] = []
    for dish_pk, component in components:
        recipe = graph_recipes[component.recipe_id]
        for line in flatten_recipe(recipe, factor=component.servings, exclude_staples=False):
            contributors.setdefault(line.ingredient.pk, set()).add(dish_pk)
            all_lines.append(line)

    kept: list[FlatLine] = []
    staples_skipped = 0
    for line in aggregate(all_lines):
        if exclude_staples and line.ingredient.is_staple:
            staples_skipped += 1
            continue
        kept.append(line)

    return _ShoppingLines(
        kept=kept,
        contributors=contributors,
        dish_by_id={dish.pk: visible[dish.pk] for dish in requested},
        staples_skipped=staples_skipped,
    )


@dataclass(frozen=True)
class ShoppingPreview:
    """What ``populate_shopping_list`` *would* write, without writing it — the meal planner's
    "see the ingredients before committing" (task 08 ``design.md``, "API":
    ``preview-shopping-list``).
    """

    lines: list[FlatLine]
    staples_skipped: int


def preview_shopping_list(
    owner: object, dishes: Sequence[Dish], *, exclude_staples: bool = True
) -> ShoppingPreview:
    """The aggregated ingredient lines for ``dishes`` — nothing is written, no list is touched.

    Runs the exact flatten / aggregate / staples path ``populate_shopping_list`` uses, so a
    preview never disagrees with the list a subsequent write produces.
    """
    computed = _flatten_dishes_to_lines(owner, dishes, exclude_staples=exclude_staples)
    return ShoppingPreview(lines=computed.kept, staples_skipped=computed.staples_skipped)


# --- merge / clear -------------------------------------------------------------------------


@transaction.atomic
def merge_duplicate_items(lst: List) -> int:
    """Combine same-ingredient item lines whose units can be reconciled, summing quantities.

    Offered as an explicit action, never done automatically: silently folding a user's own
    hand-typed line into a generated one is surprising (design.md, "``merge_duplicate_items``").
    Lines whose units cannot be converted without inventing data stay separate — the same rule
    as task 05's aggregation (D34). Returns the number of item rows removed.
    """
    mergeable = list(
        lst.items.filter(
            ingredient__isnull=False, quantity__isnull=False, unit__isnull=False
        ).select_related("ingredient", "unit")
    )
    groups: dict[int, list[ListItem]] = {}
    for item in mergeable:
        groups.setdefault(item.ingredient_id, []).append(item)

    removed = 0
    for group in groups.values():
        if len(group) > 1:
            removed += _merge_one_ingredient(group)
    return removed


def _merge_one_ingredient(items: list[ListItem]) -> int:
    """Bucket ``items`` (all for one ingredient) by unit-convertibility, then collapse each
    bucket with more than one item into its first row. Returns rows removed.
    """
    ingredient = items[0].ingredient
    buckets: list[list[ListItem]] = []
    totals: list[Decimal] = []
    for item in items:
        for index, bucket in enumerate(buckets):
            try:
                converted = convert(item.quantity, item.unit, bucket[0].unit, ingredient)
            except IncompatibleUnits:
                continue
            totals[index] += Decimal(converted)
            bucket.append(item)
            break
        else:
            buckets.append([item])
            totals.append(Decimal(item.quantity))

    removed = 0
    for bucket, total in zip(buckets, totals, strict=True):
        if len(bucket) < 2:
            continue
        keeper = bucket[0]
        keeper.quantity = total
        # The user's own line wins, so a later regeneration does not silently drop the merge.
        if any(item.source == ItemSource.MANUAL for item in bucket):
            keeper.source = ItemSource.MANUAL
            keeper.generated_from = None
        keeper.save(update_fields=["quantity", "source", "generated_from"])
        for extra in bucket[1:]:
            extra.delete()
            removed += 1
    return removed


@transaction.atomic
def clear_checked(lst: List) -> int:
    """Remove every checked item from ``lst``. Returns the number removed."""
    deleted, _ = lst.items.filter(is_checked=True).delete()
    return deleted


@transaction.atomic
def set_all_checked(lst: List, *, is_checked: bool) -> int:
    """Mark **every** item on ``lst`` checked (``is_checked=True``) or unchecked in one bulk
    ``UPDATE``. Returns the number of rows actually changed (07.19).
    """
    return lst.items.exclude(is_checked=is_checked).update(is_checked=is_checked)


@transaction.atomic
def clear_all(lst: List) -> int:
    """Delete **every** item on ``lst`` — generated and hand-added alike. Returns the number
    removed. Destructive: the view puts it behind a confirm dialog (07.19).
    """
    removed, _ = lst.items.all().delete()
    return removed


@transaction.atomic
def reorder_items(lst: List, item_ids: Sequence[int]) -> None:
    """Set ``position`` to match the order of ``item_ids``. Every id must already be on
    ``lst`` — an id that is not raises ``ListError`` rather than silently doing nothing.
    """
    known = set(lst.items.values_list("id", flat=True))
    unknown = [item_id for item_id in item_ids if item_id not in known]
    if unknown:
        raise ListError(f"These items are not on this list: {sorted(unknown)}.")
    if not item_ids:
        return
    whens = [When(id=item_id, then=Value(position)) for position, item_id in enumerate(item_ids)]
    lst.items.filter(id__in=item_ids).update(
        position=Case(*whens, output_field=PositiveIntegerField())
    )


def set_item_checked(item: ListItem, *, is_checked: bool) -> ListItem:
    """Toggle one item's checked state — the core in-the-shop interaction (design.md,
    "Shopping list behaviour").
    """
    if item.is_checked != is_checked:
        item.is_checked = is_checked
        item.save(update_fields=["is_checked"])
    return item


def update_item(item: ListItem, *, quantity: Decimal | None, unit: Unit | None) -> ListItem:
    """Override a list item's ``quantity`` and ``unit`` to whatever the user will actually buy.

    An aggregated line ("2 cups chicken breast") is frequently not a buyable amount, so the
    number and the unit are the user's to correct — the app assumes nothing and never
    auto-adjusts (design.md, "Edge cases"; 07.23).

    Rules:

    - A ``unit`` with no ``quantity`` is refused: a bare unit says nothing on a shopping line.
    - ``quantity`` may be cleared to ``None`` — a plain "chicken breast" line; ``unit`` is
      cleared with it (the caller passes ``unit=None`` in that case).
    - ``quantity`` must be a finite, non-negative number that fits ``ListItem.quantity``'s
      ``max_digits=10, decimal_places=3`` field bounds. NaN / Infinity, a negative amount, or
      an over-long number all raise ``ListError`` here rather than reaching a 500 in Django's
      decimal DB-prep. DRF's ``DecimalField`` catches most of these on the REST path before the
      value arrives; the HTML view hand-parses, so the checks live here to keep one rule for
      both surfaces (``ARCHITECTURE.md``, section 6).
    - ``item.source`` is **not** touched. A ``GENERATED`` line edited by hand stays
      ``GENERATED``. A future ``populate_shopping_list`` regeneration (task 08) will overwrite
      this manual edit — the same accepted trade-off as a lost checked state, covered by the
      same regenerate warning. Whether an override should survive regeneration is a task 08
      decision, not this one.

    ``unit`` visibility is enforced at the call boundary exactly as ``ListItemSerializer``
    does — its ``Unit`` queryset on write, the HTML view resolving the posted id against
    ``Unit.objects`` — because every ``Unit`` is ``is_system`` shared vocabulary with no
    per-user scope.
    """
    if quantity is None and unit is not None:
        raise ListError("Choose a quantity before setting a unit, or clear both.")

    if quantity is not None:
        try:
            quantity = Decimal(quantity)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ListError("Enter a number for the quantity.") from exc
        if not quantity.is_finite():
            raise ListError("Enter a real number for the quantity.")
        if quantity < 0:
            raise ListError("Quantity cannot be negative.")
        if -quantity.as_tuple().exponent > _QUANTITY_DECIMAL_PLACES:
            raise ListError("Quantity can have at most 3 decimal places.")
        if abs(quantity) > _QUANTITY_MAX:
            raise ListError("That quantity is too large.")

    item.quantity = quantity
    item.unit = unit
    item.save(update_fields=["quantity", "unit"])
    return item


def move_item(lst: List, item: ListItem, direction: str) -> None:
    """Swap ``item``'s position with its neighbour above (``"up"``) or below (``"down"``).
    Touch-friendly reordering — no drag required (task 02 touch-parity rule). A no-op at a
    list boundary or for an unknown direction.
    """
    if direction not in {"up", "down"}:
        return
    siblings = sorted(lst.items.all(), key=lambda i: (i.position, i.pk))
    index = next((n for n, sib in enumerate(siblings) if sib.pk == item.pk), None)
    if index is None:
        return
    swap_with = index - 1 if direction == "up" else index + 1
    if not (0 <= swap_with < len(siblings)):
        return
    other = siblings[swap_with]
    with transaction.atomic():
        item.position, other.position = other.position, item.position
        ListItem.objects.filter(pk=item.pk).update(position=item.position)
        ListItem.objects.filter(pk=other.pk).update(position=other.position)


def clear_generated(lst: List) -> int:
    """Remove every ``GENERATED`` item from ``lst`` that is not tied to a specific meal plan —
    the lines ``add_dish_to_list`` produced. ``MANUAL`` items are untouched. Returns the count
    removed.

    Task 08 owns the real "regenerate from the meal planner" flow (``populate_shopping_list``
    scoped to a ``source_plan``); until then this is the manual counterpart the shopping
    screen's "clear generated" control calls, behind the checked-items confirmation
    (``_regenerate_confirm.html``).
    """
    with transaction.atomic():
        removed, _ = lst.items.filter(
            source=ItemSource.GENERATED, generated_from__isnull=True
        ).delete()
    return removed


# --- UI presentation helpers (07.9–07.13) --------------------------------------------------

_KIND_ORDER = (ListKind.SHOPPING, ListKind.MEAL_PLAN, ListKind.MENU, ListKind.GENERIC)

#: Items past this many on one shopping list are paginated (design.md, "Edge cases": "paginate
#: above ~200 items").
SHOPPING_PAGE_SIZE = 200

UNTAGGED_AISLE = "Other"


@dataclass(frozen=True)
class KindGroup:
    kind: str
    label: str
    lists: list[List]


@dataclass(frozen=True)
class AisleGroup:
    name: str
    items: list[ListItem]


def list_index(user: object) -> list[KindGroup]:
    """Every list visible to ``user``, grouped by kind in a stable order. Each list carries an
    ``item_total`` / ``checked_total`` — a plain count of lines, never content, so nothing here
    can leak an invisible reference. The default shopping list is pinned to the top of its
    group.
    """
    lists = (
        List.objects.visible_to(user)
        .select_related("owner")
        .annotate(
            item_total=Count("items", distinct=True),
            checked_total=Count("items", filter=Q(items__is_checked=True), distinct=True),
        )
    )
    labels = dict(ListKind.choices)
    by_kind: dict[str, list[List]] = {}
    for lst in lists:
        by_kind.setdefault(lst.kind, []).append(lst)

    groups: list[KindGroup] = []
    for kind in _KIND_ORDER:
        bucket = by_kind.get(kind)
        if not bucket:
            continue
        bucket.sort(key=lambda item: (not item.is_default_shopping_list, item.name.lower()))
        groups.append(KindGroup(kind=kind, label=labels[kind], lists=bucket))
    return groups


def annotate_display(items: list[ListItem], *, viewer: object) -> None:
    """Attach template-facing display attributes to each item, resolving every recipe / dish /
    ingredient reference against what ``viewer`` can see in three queries total (never one
    ``visible_to`` per item):

    - ``display_label`` — the item's own ``text`` if any, else the referenced object's name if
      visible, else a ``"(hidden …)"`` placeholder that never reveals the real name.
    - ``content_hidden`` — the reference exists but is not visible to ``viewer``.
    - ``is_generated`` — came from a meal plan / add-dish, styled apart from a manual line.
    - ``display_aisle`` — the ingredient's primary tag, or ``UNTAGGED_AISLE``.

    The contributing dish is still recorded on ``ListItem.dish`` (07.5) but no "from …" caption
    is derived here: the list UI stopped rendering one in the 2026-09-05 dev-test round, and
    task 08 owns bringing a planner-generated provenance display back (07.21).
    """
    from lists.serializers import visible_item_target_caches

    caches = visible_item_target_caches(items, viewer)
    vis_recipe = caches["_visible_recipe_ids"]
    vis_dish = caches["_visible_dish_ids"]
    vis_ingredient = caches["_visible_ingredient_ids"]

    for item in items:
        hidden = False
        if item.text:
            label = item.text
        elif item.ingredient_id:
            if item.ingredient_id in vis_ingredient and item.ingredient is not None:
                label = item.ingredient.name
            else:
                label, hidden = "(hidden ingredient)", True
        elif item.recipe_id:
            if item.recipe_id in vis_recipe and item.recipe is not None:
                label = item.recipe.name
            else:
                label, hidden = "(hidden recipe)", True
        elif item.dish_id:
            if item.dish_id in vis_dish and item.dish is not None:
                label = item.dish.name
            else:
                label, hidden = "(hidden dish)", True
        else:
            label = "(empty item)"

        item.display_label = label
        item.content_hidden = hidden
        item.is_generated = item.source == ItemSource.GENERATED

        aisle = UNTAGGED_AISLE
        if not hidden and item.ingredient_id and item.ingredient is not None:
            primary_tag = next(iter(item.ingredient.tags.all()), None)
            if primary_tag is not None:
                aisle = primary_tag.name
        item.display_aisle = aisle


def group_by_aisle(items: Iterable[ListItem], *, viewer: object) -> list[AisleGroup]:
    """Group shopping-list ``items`` by their ingredient's primary tag so the list follows a
    supermarket's shape. Anything without a tagged, visible ingredient falls into
    ``UNTAGGED_AISLE``; every group is sorted alphabetically by label — the documented fallback
    when items are untagged (design.md, "Grouping"). Named aisles come first, alphabetically;
    ``UNTAGGED_AISLE`` last. Items are decorated by ``annotate_display`` as a side effect.
    """
    items = list(items)
    annotate_display(items, viewer=viewer)

    buckets: dict[str, list[ListItem]] = {}
    for item in items:
        buckets.setdefault(item.display_aisle, []).append(item)

    ordered = sorted(name for name in buckets if name != UNTAGGED_AISLE)
    if UNTAGGED_AISLE in buckets:
        ordered.append(UNTAGGED_AISLE)

    return [
        AisleGroup(
            name=name,
            items=sorted(buckets[name], key=lambda i: i.display_label.lower()),
        )
        for name in ordered
    ]
