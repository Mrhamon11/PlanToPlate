# 06 — Dishes & RecipeBooks · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **06.1 — Extract `UserObjectStats` abstract base**
  Move the shared shape out of `RecipeStats` into `core/models.py` and refactor `RecipeStats`
  onto it. Task 05's stats tests must still pass unchanged.
  *Files:* `core/models.py`, `recipes/models.py`, migration
  *Done when:* the task 05 suite is green with no test edits.

- [ ] **06.2 — `Dish` and `DishComponent`**
  Models, `servings` validator, `PROTECT` on recipe, ordering, task 03 hooks.
  *Files:* `meals/models.py`

- [ ] **06.3 — `DishStats`**
  On the new abstract base.
  *Files:* `meals/models.py`

- [ ] **06.4 — Dish derived properties**
  `total_minutes`, `roles`, and `flatten()` delegating to task 05 scaled by `servings`.
  *Files:* `meals/services/dishes.py`
  *Done when:* a two-recipe dish flattens to correctly combined, aggregated ingredients.

- [ ] **06.5 — `RecipeBook` and `RecipeBookEntry`**
  Models, `unique_together`, section, ordering, `default_ordering` preference, hooks.
  *Files:* `meals/models.py`

- [ ] **06.6 — Serializers**
  Dish with nested components, book with grouped entries, both validating visibility of every
  referenced recipe.
  *Files:* `meals/serializers.py`

- [ ] **06.7 — API viewsets**
  Both resources, plus add/remove/reorder for books and `flattened`/`made`/`stats` for dishes.
  *Files:* `meals/api.py`, `meals/filters.py`, `meals/urls.py`

- [ ] **06.8 — Dish UI**
  List, detail with combined ingredients, form with typeahead, servings and reordering.
  *Files:* `meals/views.py`, `templates/meals/dish_*.html`

- [ ] **06.9 — RecipeBook UI**
  Shelf list, section-grouped detail, ordering selector, add/remove, up/down reorder.
  *Files:* `templates/meals/recipebook_*.html`

- [ ] **06.10 — "Add to book" from recipe detail**
  A dropdown on the task 05 recipe page posting into a book.
  *Files:* `templates/recipes/_partials/_add_to_book.html`, `meals/views.py`

- [ ] **06.11 — Copy warning for large books**
  Confirmation naming the number of recipes that will be copied.
  *Files:* `templates/meals/_partials/_copy_book_confirm.html`

- [ ] **06.12 — Update the living document**
  Task 06 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
