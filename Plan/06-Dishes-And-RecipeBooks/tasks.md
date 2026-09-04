# 06 — Dishes & RecipeBooks · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **06.1 — Extract `UserObjectStats` abstract base**
  Move the shared shape out of `RecipeStats` into `core/models.py` and refactor `RecipeStats`
  onto it. Task 05's stats tests must still pass unchanged.
  *Files:* `core/models.py`, `recipes/models.py`, migration
  *Done when:* the task 05 suite is green with no test edits.
  *Follow-up:* see 06.12 — the abstract base changed a task-05 reverse accessor name.

- [x] **06.2 — `Dish` and `DishComponent`**
  Models, `servings` validator, `PROTECT` on recipe, ordering, task 03 hooks.
  *Files:* `meals/models.py`

- [x] **06.3 — `DishStats`**
  On the new abstract base.
  *Files:* `meals/models.py`

- [x] **06.4 — Dish derived properties**
  `total_minutes`, `roles`, and `flatten()` delegating to task 05 scaled by `servings`.
  *Files:* `meals/services/dishes.py`
  *Done when:* a two-recipe dish flattens to correctly combined, aggregated ingredients.

- [x] **06.5 — `RecipeBook` and `RecipeBookEntry`**
  Models, `unique_together`, section, ordering, `default_ordering` preference, hooks.
  *Files:* `meals/models.py`

- [x] **06.6 — Serializers**
  Dish with nested components, book with grouped entries, both validating visibility of every
  referenced recipe.
  *Files:* `meals/serializers.py`

- [x] **06.7 — API viewsets**
  Both resources, plus add/remove/reorder for books and `flattened`/`made`/`stats` for dishes.
  *Files:* `meals/api.py`, `meals/filters.py`, `meals/urls.py`

- [x] **06.8 — Dish UI**
  List, detail with combined ingredients, form with typeahead, servings and reordering.
  *Files:* `meals/views.py`, `templates/meals/dish_*.html`
  *Round-2 review findings to close in this stage (code is warm and these files are in play):*
  - **N+1 on the dish list.** `DishSerializer._visible_components` runs one
    `Recipe.objects.visible_to(user)` per row (~21 queries / 10 dishes); the per-render memo is
    keyed by `obj.pk` so it does not help across a page. Resolve the visible recipe ids once
    for the whole page. Same fix applies to the book list in 06.9. Add a list query-count test
    (see test-plan) — currently only the flatten path is budgeted.
  - **Enumeration signal on dish-component writes.** `DishComponentSerializer.recipe` uses the
    unrestricted `Recipe.objects.all()`, so an invisible-but-existing id and a nonexistent id
    give distinguishable 400 messages. Scope the field queryset to `visible_to` like
    `AddRecipeToBookSerializer` already does, or normalize the message.
  - **`remove_recipe` 500 on a non-numeric URL segment.** `meals/api.py` passes the raw
    `recipe_id` into `.filter(recipe_id=...)`; a non-numeric value raises `ValueError` → 500.
    Coerce to int (or `try/except`) and return 404.
  - **Viewer-agnostic model properties.** `Dish.total_minutes` / `Dish.roles` call
    `dish.components.all()` unfiltered. No leak today (the serializer uses the
    `total_minutes_for` / `roles_for` helpers over visible components), but add a docstring
    note like the one already on `flatten()` so a future view does not use the bare property.

- [x] **06.9 — RecipeBook UI**
  Shelf list, section-grouped detail, ordering selector, add/remove, up/down reorder.
  *Files:* `templates/meals/recipebook_*.html`
  *Round-2 review finding:* same N+1 as 06.8 in `RecipeBookSerializer._visible_entries`
  (~20 queries / 10 books). Fix it with the same page-wide id resolution and cover it with the
  book half of the list query-count test.

- [x] **06.10 — "Add to book" from recipe detail**
  A dropdown on the task 05 recipe page posting into a book.
  *Files:* `templates/recipes/_partials/_add_to_book.html`, `meals/views.py`

- [x] **06.11 — Copy warning for large books**
  Confirmation naming the number of recipes that will be copied.
  *Files:* `templates/meals/_partials/_copy_book_confirm.html`
  *Also:* re-check `meals/services/stats.py::toggle_favorite` — a deferred round-1 review
  finding. It is currently unused, kept deliberately parallel with `recipes.services.stats`.
  If the dish UI (06.8–06.11) wires it, keep it; if still unused once the UI is in, delete it.
  → **kept:** `DishFavoriteView` (dish detail "Add to favourites") now calls it.

- [x] **06.12 — Resolve the `RecipeStats` reverse-accessor rename** *(round-2 review, NB2)*
  → **Resolved by the clean rename.** `UserObjectStats.user` `related_name` is now
  `"%(class)s_records"` (→ `user.recipestats_records` / `user.dishstats_records`). Migration
  `recipes/0003_alter_recipestats_user` regenerated in place; `meals/0001_initial` (not yet
  committed) edited to match — no extra migration. `makemigrations --check` clean. Grep across
  the repo confirmed nothing reads the reverse accessor (`services.stats` modules always query
  the concrete model). Local dev DB **not** migrated (needs permission per CLAUDE.md §2, and the
  test DB rebuilds from migrations anyway).
  The `UserObjectStats` abstract base (06.1) uses `related_name="%(class)ss"`, which silently
  renamed task 05's `user.recipe_stats` to `user.recipestatss` and adds `user.dishstatss`.
  Nothing references the reverse accessor today and the migration (`0003_alter_recipestats_user`)
  is reversible, but it is an undocumented deviation from task 05 and the name is awkward.
  **Must be settled before the task-06 PR merges** — while the base's `related_name` can still
  change inside this branch's migration rather than costing a second one post-merge.
  *Decision:* either give the base a clean `related_name` (e.g. `"%(class)s_records"` →
  `user.recipestats_records` / `user.dishstats_records`, or a per-subclass override restoring
  `recipe_stats`), regenerate the migration, and grep for any `recipe_stats` reverse use; **or**
  accept `recipestatss` and record the rename in the MILESTONES row for 06.1.
  *Files:* `core/models.py`, `recipes/models.py`, `meals/models.py`, migration

- [x] **06.13 — Update the living document**
  Task 06 → COMPLETE (reviewed, dev-tested and approved by the owner).
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`
