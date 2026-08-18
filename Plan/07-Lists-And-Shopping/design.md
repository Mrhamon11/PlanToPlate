# 07 — Lists & Shopping · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Lists that hold anything — free text, Recipes, Dishes, Ingredients — plus the shopping list
behaviour that the meal planner will drive.

**Depends on:** 06-Dishes-And-RecipeBooks.
**Enables:** 08-Meal-Planner.

## Models

```python
class ListKind(models.TextChoices):
    SHOPPING = "SHOPPING"; MEAL_PLAN = "MEAL_PLAN"
    MENU = "MENU"; GENERIC = "GENERIC"


class List(OwnedModel):
    name = models.CharField(max_length=200)
    kind = models.CharField(choices=ListKind.choices, default=GENERIC, db_index=True)
    is_default_shopping_list = models.BooleanField(default=False)


class ListItem(models.Model):
    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField(default=0)
    is_checked = models.BooleanField(default=False)

    text = models.CharField(max_length=500, blank=True)
    recipe = models.ForeignKey(Recipe, on_delete=models.SET_NULL, null=True, blank=True)
    dish = models.ForeignKey(Dish, on_delete=models.SET_NULL, null=True, blank=True)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True)

    source = models.CharField(choices=ItemSource.choices, default=MANUAL, db_index=True)
    generated_from = models.ForeignKey("planner.MealPlan", on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name="generated_items")

    class Meta:
        ordering = ["position"]
        constraints = [
            models.CheckConstraint(
                condition=Q(text__gt="") | Q(recipe__isnull=False)
                        | Q(dish__isnull=False) | Q(ingredient__isnull=False),
                name="list_item_has_content",
            )
        ]
```

**Explicit nullable foreign keys, not a generic `ContentType` relation.** Four columns is
slightly less elegant than a generic FK, but it gives real database constraints, real indexes,
`select_related` in one query, and filters that read plainly. Generic relations here would buy
flexibility the requirements never ask for and cost clarity on every single query.

`SET_NULL` on the content FKs: deleting a recipe should not silently delete a line from
someone's shopping list. The item survives with its text/quantity, and the UI renders it as
"(deleted recipe)". Losing a line off a list you are standing in a shop holding is worse than
seeing a tombstone.

`PROTECT` on `unit`, matching every other model.

### `source` and `generated_from`

`MILESTONES.md` C8 — the single most important thing in this task. Regenerating a meal plan
must not append a second copy of every ingredient.

- `MANUAL` — the user typed it. **Never touched by regeneration.**
- `GENERATED` — produced by a meal plan. Replaced wholesale on regeneration.

The requirements did not mention this at all, which is exactly why the second week of use
would have produced a shopping list with everything on it twice.

### The default shopping list

The requirement: generated ingredients go to a designated shopping list, created and named
"Shopping List" if none exists.

`is_default_shopping_list` marks it. A service, `get_or_create_default_shopping_list(user)`,
handles the creation. A `UniqueConstraint` on `(owner, is_default_shopping_list)` filtered to
`True` guarantees at most one per user — the alternative, checking in application code, drifts
the first time two requests race.

## Services — `lists/services.py`

```python
def get_or_create_default_shopping_list(user) -> List
def add_dish_to_list(lst, dish, *, actor) -> list[ListItem]
def add_recipe_to_list(lst, recipe, *, actor) -> list[ListItem]
def populate_shopping_list(lst, dishes, *, source_plan=None,
                           exclude_staples=True, replace_generated=True) -> ShoppingResult
def merge_duplicate_items(lst) -> int
def clear_checked(lst) -> int
```

**`populate_shopping_list` is the task 08 contract.** It:

1. Flattens every dish via task 06 (which recurses through task 05's sub-recipe scaling).
2. Aggregates across all dishes — one line per ingredient for the whole week, not one per meal.
3. Optionally drops staples.
4. If `replace_generated`, deletes existing `GENERATED` items **belonging to `source_plan`**
   before inserting. Scoping the delete to the plan means two plans can feed one list without
   trampling each other.
5. Leaves every `MANUAL` item untouched.
6. Runs in one transaction.
7. Returns a summary — items added, items replaced, staples skipped — so the UI can say what
   happened instead of silently mutating a list.

`merge_duplicate_items` handles the manual case: a user adds "milk" by hand and then generates
a plan that also needs milk. Offered as an explicit action rather than done automatically,
because silently merging a user's own line into a generated one is surprising.

## Shopping list behaviour

- **Check off** — `is_checked`, toggled via HTMX with no page reload. The core in-the-shop
  interaction, so it must be fast and forgiving on a bad phone connection.
- **Grouping** — items grouped by the ingredient's primary tag (produce, dairy, meat, pantry)
  so the list follows the shape of a supermarket. Fall back to alphabetical when untagged.
- **Sticky totals** — "12 of 20 items."
- **Clear checked** — bulk removal.
- **Provenance** — a generated item shows what it came from ("from Chicken Parm"), which is
  what makes a surprising line understandable rather than suspicious.

## API

| Route | Notes |
|---|---|
| `GET/POST /api/lists/` | Filter by `kind`, plus the standard owned filters |
| `GET/PUT/PATCH/DELETE /api/lists/<id>/` | |
| `POST /api/lists/<id>/items/` | Add an item |
| `PATCH /api/lists/<id>/items/<item_id>/` | Edit, check/uncheck |
| `DELETE /api/lists/<id>/items/<item_id>/` | |
| `PATCH /api/lists/<id>/reorder/` | Bulk positions |
| `POST /api/lists/<id>/add-dish/` | Expands a dish to ingredients |
| `POST /api/lists/<id>/clear-checked/` | |
| `POST /api/lists/<id>/merge-duplicates/` | |
| `GET /api/lists/default-shopping/` | Get or create |

## UI

- **List index** — grouped by kind, item counts, a pinned default shopping list.
- **Shopping list detail** — the most-used screen in the app on a phone: large tap targets,
  aisle grouping, sticky progress, one-tap check, quick-add at the top, provenance as
  secondary text, and generated items visually distinguished from manual ones.
- **Generic list detail** — mixed items with type icons, inline add of text/recipe/dish, up/down
  reordering.
- **"Add to list ▾"** on recipe and dish detail pages.

## Edge cases

- Adding a dish twice: aggregates into existing generated lines rather than duplicating.
- Checking an item then regenerating: **the checked state of a replaced generated item is
  lost.** Acceptable and documented — but the UI must warn before regenerating a list with
  checked items, because losing your shopping progress mid-trip is a genuinely bad surprise.
- An item with a quantity but no unit (a bare "3 lemons"): allowed; `unit` is nullable.
- An item with neither text nor any FK: rejected by the check constraint.
- Deleting a recipe referenced by list items: `SET_NULL`, item survives as a tombstone.
- A list shared with another user: they see it read-only and **cannot check items off**.
  Collaborative editing is explicitly out of scope — task 03 grants read, not write, and a
  shared shopping list two people both tick is a different feature with concurrency questions
  this app does not need.
- An enormous generated list (a 7-day plan of 4-recipe dishes): paginate above ~200 items.

## Security notes

- Standard task 03 protection on `List`; items inherit visibility from their list.
- **Every FK on an item must be validated as visible to the actor** — the same read primitive
  as task 06. Attaching a guessed recipe ID to your own list and reading it back is the attack.
- `populate_shopping_list` must verify the actor can see every dish it is asked to expand.
- Item counts and previews on the list index must not leak invisible content.
