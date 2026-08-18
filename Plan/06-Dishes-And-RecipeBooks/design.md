# 06 — Dishes & RecipeBooks · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Two ways of grouping recipes: a **Dish** (the recipes that make one meal) and a **RecipeBook**
(a user-organised collection). Both are thin over task 05, which is the point — the heavy
lifting already exists.

**Depends on:** 05-Recipes.
**Enables:** 07, 08, N3.

## Dish

```python
class Dish(OwnedModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True)

class DishComponent(models.Model):
    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, related_name="components")
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT)
    servings = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    position = models.PositiveIntegerField(default=0)

class DishStats(models.Model):        # identical shape to RecipeStats
    user, dish, rating, is_favorite, times_made, last_made_at
```

`servings` is the scale factor for that recipe within this dish — a dish for six uses the
same recipes as a dish for two at a different multiple. Without it, "Taco Night" always
generates a shopping list for whatever the recipe author assumed.

`DishStats` mirrors `RecipeStats` exactly. **Factor the shared behaviour into an abstract
`UserObjectStats` base in `core/`** rather than copying the model — and refactor `RecipeStats`
onto it as part of this task. Two copies of this model is how the third one gets written
subtly differently.

### Derived properties

- `total_minutes` — the max of prep across components plus the sum of cook, which is closer to
  reality than summing everything, since a cook works on things in parallel. Approximate, and
  labelled as such in the UI.
- `roles` — the set of component recipe roles, used by the planner to check a dish against a
  `BALANCED` template.
- `flatten()` — delegates to task 05's flattener per component, scaled by `servings`, then
  `aggregate`s across the whole dish. **The shopping list's entry point.**

## RecipeBook

```python
class RecipeBook(OwnedModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

class RecipeBookEntry(models.Model):
    book = models.ForeignKey(RecipeBook, on_delete=models.CASCADE, related_name="entries")
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE)
    section = models.CharField(max_length=100, blank=True)    # "Weeknight", "Desserts"
    position = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("book", "recipe")]
        ordering = ["section", "position"]
```

The requirement was that users organise recipes "how they want — category, cuisine,
alphabetically." That is two separate things:

- **`section`** — a free-text grouping the user invents per book. Not a global taxonomy;
  Alice's "Quick" need not mean Bob's "Quick", and forcing a shared vocabulary here would be
  the wrong kind of rigour.
- **Sort order** — a view-level choice (manual position, name, rating, time, times-made),
  stored as the book's `default_ordering` preference.

`unique_together` stops the same recipe appearing twice in one book. A recipe may of course
live in any number of *different* books, as required.

`on_delete=CASCADE` here, unlike `DishComponent`'s `PROTECT`: removing a recipe from a book is
a filing change, not a data loss, so a deleted recipe should quietly leave its books rather
than blocking its own deletion.

## Sharing and copying

Both models implement the task 03 hooks:

- `Dish.share_dependencies()` → its recipes (which transitively pull in their sub-recipes and
  ingredients).
- `RecipeBook.share_dependencies()` → its recipes.
- `copy_children()` → deep-copies recipes for a Dish. **For a RecipeBook, copying deep-copies
  every recipe too** — otherwise copying a 60-recipe book silently creates 60 dependencies on
  another user's data, and task 03 chose independence over cleverness. The UI must warn about
  the volume before doing it.

## API

| Route | Notes |
|---|---|
| `GET/POST /api/dishes/` | Filters: `search`, `tags`, `role`, `favorite`, `mine`, … |
| `GET/PUT/PATCH/DELETE /api/dishes/<id>/` | Components written nested |
| `GET /api/dishes/<id>/flattened/` | Aggregated ingredients across the dish |
| `POST /api/dishes/<id>/made/` · `PUT .../stats/` | |
| `POST /api/dishes/<id>/copy/` · `share/` | |
| `GET/POST /api/recipe-books/` | |
| `POST /api/recipe-books/<id>/recipes/` | Add — `{recipe, section}` |
| `DELETE /api/recipe-books/<id>/recipes/<recipe_id>/` | Remove |
| `PATCH /api/recipe-books/<id>/reorder/` | Bulk position update |
| `GET /api/recipe-books/<id>/?ordering=name` | |

## UI

**Dish** — list of cards showing component recipes and total time; detail showing each recipe
with its servings, combined ingredients, and a "make this" action; a form with recipe
typeahead (visibility-filtered), servings, and up/down reordering.

**RecipeBook** — a shelf-style list; detail grouped by section with an ordering selector and a
recipe grid; drag-to-reorder on desktop with up/down buttons always present for touch. Adding
a recipe from the recipe detail page ("Add to book ▾") is the path most people will actually
use, so it gets built here rather than being left implicit.

## Edge cases

- An empty dish: allowed to exist while being built, but the planner (08) must skip dishes with
  no components rather than proposing a meal of nothing.
- A dish whose recipes are all the same role: legal, but a `BALANCED` planner template will not
  select it. Not an error.
- Removing the last recipe from a book leaves an empty book, which is fine.
- `servings` of zero: rejected — it contributes nothing and hides a data-entry mistake.
- Deleting a recipe used in a dish: `PROTECT` → 409 naming the dishes.
- Copying a large book: warn above ~20 recipes, since it is a slow, heavy operation.
- `total_minutes` with no components is zero, not an error.

## Security notes

- Same nested-write validation as task 05: every referenced recipe must be `visible_to` the
  requester. **Adding a recipe to a book is the sneakiest read primitive in the app** — if
  unvalidated, a user could add a guessed recipe ID to their own book and read it back through
  the book detail page.
- Book and dish detail serializers expand recipes through `visible_to`, never raw.
- `DishStats` is per-user and private, exactly as `RecipeStats`.
