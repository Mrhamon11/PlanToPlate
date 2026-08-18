# 05 — Recipes · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

The central model of the application: a recipe of ingredients and sub-recipes with quantities,
a yield, instructions, and per-user stats. Plus the scaling and flattening service that the
shopping list and meal planner both depend on.

**Depends on:** 04-Units-And-Ingredients.
**Enables:** 06, 07, 08, N1, N2.

## Models

```python
class RecipeRole(models.TextChoices):
    PROTEIN = "PROTEIN"; CARB = "CARB"; VEGETABLE = "VEGETABLE"
    ONE_POT = "ONE_POT"; SAUCE = "SAUCE"; DESSERT = "DESSERT"
    SIDE = "SIDE"; BREAKFAST = "BREAKFAST"; OTHER = "OTHER"


class Recipe(OwnedModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    instructions = models.TextField()                       # markdown-ish, rendered escaped
    yield_quantity = models.DecimalField(max_digits=10, decimal_places=3)
    yield_unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    prep_minutes = models.PositiveIntegerField(default=0)
    cook_minutes = models.PositiveIntegerField(default=0)
    role = models.CharField(choices=RecipeRole.choices, default=OTHER, db_index=True)
    tags = models.ManyToManyField(Tag, blank=True)
    source_url = models.URLField(blank=True)                # used by task N2
```

### Yield is mandatory

`MILESTONES.md` C1. "1 cup of marinara" cannot be turned into a shopping list unless the
marinara recipe declares what it makes. Without a yield, sub-recipes are decorative and the
whole recursive-recipe feature — a headline requirement — does not actually work.

Yield also gives scaling ("cook this for 8 instead of 4") for free, so it earns its place twice.

Sensible default in the form: `4` `serving`.

### `role` is explicit

`MILESTONES.md` C7. The planner needs to know a Protein from a Carb. Deriving it from
ingredients is fragile and fails on exactly the interesting cases (a chicken *stock* is not a
protein dish; a bean salad might be either). The form may **suggest** a role from the
ingredient tags, but the user's choice is what is stored.

### Components

```python
class RecipeComponent(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="components")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, null=True, blank=True)
    sub_recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="used_in")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    position = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)     # "finely diced"

    class Meta:
        ordering = ["position"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(ingredient__isnull=False) & Q(sub_recipe__isnull=True))
                        | (Q(ingredient__isnull=True) & Q(sub_recipe__isnull=False)),
                name="component_ingredient_xor_subrecipe",
            )
        ]
```

`PROTECT` on both: deleting an ingredient or a recipe that something else depends on must
fail loudly with a message naming the dependents (task 04's 409 pattern), not silently gut
someone's recipe.

### Per-user stats

```python
class RecipeStats(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="stats")
    rating = models.PositiveSmallIntegerField(null=True, blank=True)   # 1–5
    is_favorite = models.BooleanField(default=False)
    times_made = models.PositiveIntegerField(default=0)
    last_made_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("user", "recipe")]
```

`MILESTONES.md` D3/C4. Rows are created lazily — most users never rate most recipes, and a row
per user per recipe up front is waste. Access through
`RecipeStats.objects.get_or_create(user=…, recipe=…)` behind a small service so the laziness is
not every caller's problem.

`last_made_at` is what the planner's `no_repeat_days` gear (gear 6) reads.

## The cycle guard

`MILESTONES.md` C2. A recipe graph is a DAG; nothing in the requirements stopped it becoming
cyclic, and a cycle makes flattening recurse until the stack dies.

`recipes/services/graph.py`:

```python
MAX_DEPTH = 5

def assert_no_cycle(recipe, candidate_sub_recipe) -> None
def recipe_depth(recipe) -> int
```

- `assert_no_cycle` runs **on every write path** that adds or changes a `sub_recipe` — the
  serializer, the form, the admin, and any bulk import. Enforcing it in only one of those is
  how the bad row eventually gets in.
- A recipe may never contain itself, directly or transitively.
- `MAX_DEPTH = 5` is a practical ceiling. Beyond that, flattening is slow and the recipe is
  probably a mistake. The error names the chain that broke it.

## Scaling and flattening

`recipes/services/flatten.py` — used by the shopping list (07) and the meal planner (08). The
most load-bearing service in the project.

```python
@dataclass(frozen=True)
class FlatLine:
    ingredient: Ingredient
    quantity: Decimal
    unit: Unit
    from_recipes: tuple[str, ...]      # provenance, for "1 cup — from Marinara, Meatballs"

def scale(recipe, factor: Decimal) -> list[RecipeComponent]        # unsaved, scaled
def flatten(recipe, *, factor=ONE, exclude_staples=False) -> list[FlatLine]
def aggregate(lines: Iterable[FlatLine]) -> list[FlatLine]
```

**The flatten algorithm:**

1. Walk `recipe.components`.
2. An ingredient component emits a `FlatLine` scaled by the current factor.
3. A sub-recipe component computes its own factor:
   `sub_factor = convert(component.quantity, component.unit, sub.yield_unit) / sub.yield_quantity`
   then recurses with `factor * sub_factor`. **This is the step yield exists for.**
4. Cycle-guarded and depth-capped, reusing `graph.py`.
5. `aggregate` groups by `(ingredient, dimension)`, sums in base units, converts back to the
   most human-friendly unit for the total, and merges provenance.
6. Lines whose dimensions cannot be reconciled (200 g flour + 2 cups flour, no density) stay
   **separate**, each labelled. Two honest lines beat one fabricated number.
7. `exclude_staples` drops `ingredient.is_staple` rows.

Performance: `prefetch_related` the component/ingredient/unit graph up front. Flattening a
week of dinners must not fire hundreds of queries — there is a query-count test for this.

## API

| Route | Notes |
|---|---|
| `GET/POST /api/recipes/` | Filters: `search`, `tags`, `role`, `max_minutes`, `min_rating`, `favorite`, `mine`, `shared_with_me`, `public` |
| `GET/PUT/PATCH/DELETE /api/recipes/<id>/` | Components written nested in one request |
| `POST /api/recipes/<id>/copy/` · `share/` · `unshare/` | From `OwnedViewSetMixin` |
| `GET /api/recipes/<id>/scaled/?factor=2` | Scaled components, nothing persisted |
| `GET /api/recipes/<id>/flattened/?exclude_staples=true` | The aggregated ingredient list |
| `POST /api/recipes/<id>/made/` | Increments `times_made`, stamps `last_made_at` |
| `PUT /api/recipes/<id>/stats/` | Set rating and favourite |

Components are edited as a nested write on the recipe: replace-the-set semantics inside one
transaction. Separate component endpoints would let a client leave a recipe half-saved.

## UI

- **Recipe list** — cards with role and time badges, favourite star, rating; debounced search
  and filter chips.
- **Recipe detail** — ingredients (with a scale control that re-renders quantities via HTMX,
  persisting nothing), instructions, times, tags, notes, "I made this" button, rating widget,
  and a **sub-recipe expander** that inlines a sub-recipe's ingredients without leaving the page.
- **Recipe form** — the substantial screen:
  - Component rows added/removed via HTMX, each row being ingredient-or-sub-recipe, quantity,
    unit, note.
  - Ingredient typeahead against `visible_to`, with task 04's quick-add inline when nothing
    matches.
  - Sub-recipe typeahead **excluding anything that would create a cycle** — the server filters
    the candidate list, so the illegal choice is not merely rejected, it is never offered.
  - Reorder with up/down buttons (touch parity, per task 02); drag is a desktop enhancement.
  - Required yield with a sensible default.
- **Print view** — a clean, ink-light stylesheet. People cook from paper.

## Edge cases

- Yield of zero: rejected. It is a division by zero in step 3 of flatten.
- Sub-recipe whose yield unit is a different dimension from the component's unit: refuse at
  validation with a clear message, since the factor is uncomputable.
- Deleting a recipe used as a sub-recipe: 409 naming the parents.
- Copying a recipe with sub-recipes: task 03's deep copy recurses; the copy owns its whole tree.
- Sharing a recipe with a sub-recipe you do not own: task 03's cascade refuses and names the
  blocker.
- A component whose ingredient is invisible to the viewer (a shared recipe referencing a
  private ingredient): should be impossible via the share cascade, but the serializer must
  degrade to the name rather than 500. **Defence in depth for the case where the cascade has
  a bug.**
- Rating outside 1–5: validator.
- Instructions are stored as text and rendered **escaped**; if markdown rendering is added
  later it must run through a sanitiser allowlist.

## Security notes

- Sub-recipe and ingredient pickers filter through `visible_to` — a typeahead is a classic
  place to leak the existence of private objects by name.
- Nested component writes must validate that every referenced ingredient and sub-recipe is
  visible to the requester. Otherwise a user can attach an object they only guessed the ID of
  and read its contents back through their own recipe. **This is the highest-value IDOR test
  in the task.**
- `source_url` is stored but never fetched here; fetching belongs to N2, behind its SSRF guard.
- Flattening runs on user-supplied graph shapes: depth cap and cycle guard are a
  denial-of-service defence as much as a correctness one.
