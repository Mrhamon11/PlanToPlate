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

- [x] **05.7 — Serializers**
  `RecipeSerializer` with nested components (replace-set semantics, atomic),
  `RecipeComponentSerializer`, `RecipeStatsSerializer`, `FlatLineSerializer`.
  Validate visibility of every referenced ingredient and sub-recipe.
  *Files:* `recipes/serializers.py`
  *Done when:* referencing an invisible ingredient by ID is rejected.

- [x] **05.8 — API viewset**
  CRUD plus `scaled`, `flattened`, `made`, `stats`, and all filters.
  *Files:* `recipes/api.py`, `recipes/filters.py`, `recipes/api_urls.py` (API split from the
  future `recipes/urls.py` per the `catalog/api_urls.py` precedent).
  *Also:* hardened `scale` / `flatten` in `recipes/services/flatten.py` to reject a `float`
  `factor` (mirrors `catalog.services.units._as_decimal`'s `TypeError`). (Task 05 review NB2.)
  `made` / `stats` write per-user `RecipeStats`, so `core.viewsets._ACTION_PERMISSION_CLASSES`
  gained `made`/`stats` → `CanCopy` ("if you can see it, you can act"), added
  `set_favorite` to `recipes/services/stats.py`.

- [x] **05.9 — Protected-delete handling**
  409 naming parent recipes when deleting a sub-recipe in use.
  *Files:* `recipes/api.py` (`perform_destroy` maps blocking `RecipeComponent`s to their
  parent recipes before building the `core.exceptions.Conflict`).

- [x] **05.10 — Recipe list UI**
  Cards, badges, search, filter chips, favourite toggle, pagination.
  *Files:* `recipes/views.py`, `recipes/urls.py` (new, wired into `config/urls.py`),
  `templates/recipes/recipe_list.html`, `templates/recipes/_partials/_recipe_results.html`,
  `static/css/components.css`. Rating/favourite filters read the requesting user's
  `RecipeStats` (prefetched with `to_attr` for the card badges).

- [x] **05.11 — Recipe detail UI**
  Ingredients, instructions (escaped), HTMX scale control (reuses `flatten.scale`, persists
  nothing), sub-recipe expander fragment (degrades to the name when the sub-recipe is
  invisible), "I made this" / rating / favourite widgets, share (task 03 `_share_modal`) and
  copy (task 03 `_copy_button`) controls.
  *Files:* `templates/recipes/recipe_detail.html`, `templates/recipes/recipe_share.html`,
  `templates/recipes/_partials/_ingredient_list.html`,
  `templates/recipes/_partials/_subrecipe_expansion.html`, `recipes/views.py`,
  `recipes/models.py` (`get_absolute_url`).

- [x] **05.12 — Recipe form UI**
  Dynamic component rows, ingredient typeahead with quick-add, cycle-filtered sub-recipe
  typeahead, up/down reordering, yield with default.
  *Files:* `templates/recipes/recipe_form.html`, `recipes/views.py`
  *Done when:* a three-ingredient recipe with one sub-recipe can be created entirely on a
  phone-width screen.
  *Also:* the form's sub-recipe write path MUST route through `assert_no_cycle`, and
  `test_guard_enforced_on_form` (test-plan.md) must land with this subtask. Task 05 review
  left only `test_guard_enforced_on_serializer` proven; the admin path is tracked in 09.4.

- [x] **05.13 — Print stylesheet**
  Standalone ink-light document (does not extend `base.html`), `@media print` hides the
  on-screen toolbar.
  *Files:* `static/css/print.css`, `templates/recipes/recipe_print.html`

- [x] **05.15 — Dev-test rework**
  Findings from the user's manual dev test, fixed in place (not a new agent cycle):
  - **Copy `IntegrityError`** when the actor already owns a copy of a shared private
    ingredient/sub-recipe → `_copy_or_reference` reuses the existing copy (Plan/03 design
    updated; `Copier.actor` exposed).
  - **Print** omitted sub-recipe ingredients → recursive `_print_components.html`, print view
    switched to `with_component_graph()`.
  - **Delete** — there was no delete control → `RecipeDeleteView` + confirm page + shared
    `recipes.services.deletion` (REST `perform_destroy` refactored onto it).
  - Scale `<select>` kept a stale multiplier after reload → `autocomplete="off"` +
    `recipe-detail.js` `pageshow` reset.
  - Component-editor field alignment → each cell is a flex column that bottom-pins its input,
    the row stretches the cells to a common height, and the typeahead results are an absolute
    dropdown (not in flow) — so the inputs and the up/down/× controls line up regardless of the
    caption / chosen-name height above them, on mobile and desktop.
  - Sub-recipe expander is now a real +/− toggle: `recipe-detail.js` flips the `[hidden]`
    attribute on the panel (htmx `click once` fills it on first open).
  - Always-visible **Clear filters** link on the recipe list.
  Deferred to Plan/11: unshare/unpublish sub-recipe cascade (11.11), collapsible filter panel
  (11.12), typeahead keyboard nav (11.13).
  *Files:* `core/services/copying.py`, `recipes/models.py`, `recipes/views.py`, `recipes/urls.py`,
  `recipes/api.py`, `recipes/services/deletion.py`, `templates/recipes/*`, `static/js/recipe-detail.js`,
  `static/js/recipe-editor.js`, `static/css/{components,print}.css`

- [x] **05.14 — Update the living document**
  Task 05 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
  *Also reconcile in this pass (task 05 review non-blocking):*
  - `Plan/ARCHITECTURE.md` §4 data model still lists the 7-role `Recipe.role` set; the
    implementation follows `design.md`'s 9-role set (adds `SIDE`, `BREAKFAST`). Update §4 and
    add the role-set change to the decision log.
  - Record in the MILESTONES row that `FlatLine.from_recipes` carries the **full root→leaf
    recipe chain** for each line, not just the recipes that directly list the ingredient
    (locked in by `test_flatten_records_provenance`). Tasks 07/08 inherit this semantics.
