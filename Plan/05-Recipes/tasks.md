# 05 — Recipes · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **05.1 — `Recipe` model**
  `OwnedModel` subclass with yield, times, role, tags. `share_dependencies()` returns
  sub-recipes and ingredients; `copy_children()` copies components.
  *Files:* `recipes/models.py`
  *Done when:* migrations apply and the task 03 convention tests pass.

- [x] **05.2 — `RecipeComponent` model**
  With the ingredient-XOR-sub_recipe check constraint, `PROTECT` deletes, and ordering.
  *Files:* `recipes/models.py`
  *Done when:* the database rejects a component with both or neither set.

- [x] **05.3 — `RecipeStats` model and service**
  Lazy `get_or_create` accessor, `mark_made()`, `set_rating()`, `toggle_favorite()`.
  *Files:* `recipes/models.py`, `recipes/services/stats.py`

- [x] **05.4 — Cycle guard**
  `assert_no_cycle`, `recipe_depth`, `MAX_DEPTH`, and a `CycleError` naming the chain.
  *Files:* `recipes/services/graph.py`
  *Done when:* self-reference, a two-hop cycle, and a five-hop cycle are all caught.

- [x] **05.5 — Scale and flatten service**
  `scale`, `flatten`, `aggregate`, `FlatLine`, including sub-recipe yield scaling and
  irreconcilable-dimension splitting.
  *Files:* `recipes/services/flatten.py`
  *Done when:* a nested recipe flattens to correct quantities by hand-checked arithmetic.

- [x] **05.6 — Query optimisation for flatten**
  `prefetch_related` the whole component graph.
  *Files:* `recipes/services/flatten.py`, `recipes/managers.py`
  *Done when:* the query-count test passes for a 3-level, 20-component recipe.

- [ ] **05.7 — Serializers**
  `RecipeSerializer` with nested components (replace-set semantics, atomic),
  `RecipeComponentSerializer`, `RecipeStatsSerializer`, `FlatLineSerializer`.
  Validate visibility of every referenced ingredient and sub-recipe.
  *Files:* `recipes/serializers.py`
  *Done when:* referencing an invisible ingredient by ID is rejected.

- [ ] **05.8 — API viewset**
  CRUD plus `scaled`, `flattened`, `made`, `stats`, and all filters.
  *Files:* `recipes/api.py`, `recipes/filters.py`, `recipes/urls.py`
  *Also:* harden `scale` / `flatten` in `recipes/services/flatten.py` to reject a `float`
  `factor` (mirror `catalog.services.units._as_decimal`'s `TypeError`) before wiring the
  `?factor=` query param into them — a float carries binary rounding error into `Decimal`.
  (Task 05 review NB2.)

- [ ] **05.9 — Protected-delete handling**
  409 naming parent recipes when deleting a sub-recipe in use.
  *Files:* `recipes/api.py`

- [ ] **05.10 — Recipe list UI**
  Cards, badges, search, filter chips, favourite toggle, pagination.
  *Files:* `recipes/views.py`, `templates/recipes/recipe_list.html`

- [ ] **05.11 — Recipe detail UI**
  Ingredients, instructions, HTMX scale control, sub-recipe expander, "I made this", rating,
  share and copy controls.
  *Files:* `templates/recipes/recipe_detail.html`, `_partials/`

- [ ] **05.12 — Recipe form UI**
  Dynamic component rows, ingredient typeahead with quick-add, cycle-filtered sub-recipe
  typeahead, up/down reordering, yield with default.
  *Files:* `templates/recipes/recipe_form.html`, `recipes/views.py`
  *Done when:* a three-ingredient recipe with one sub-recipe can be created entirely on a
  phone-width screen.

- [ ] **05.13 — Print stylesheet**
  *Files:* `static/css/print.css`, `templates/recipes/recipe_print.html`

- [ ] **05.14 — Update the living document**
  Task 05 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
