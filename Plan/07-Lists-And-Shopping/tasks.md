# 07 — Lists & Shopping · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **07.1 — `List` model**
  `OwnedModel` subclass with `kind`, the default-shopping-list flag, and the filtered unique
  constraint. Task 03 hooks.
  *Files:* `lists/models.py`

- [ ] **07.2 — `ListItem` model**
  The four content FKs, quantity/unit, `source`, `generated_from`, and the has-content check
  constraint.
  *Files:* `lists/models.py`
  *Done when:* an item with no content of any kind is rejected by the database.

  > `generated_from` points at `planner.MealPlan`, which does not exist yet. Use a string
  > reference and let task 08 supply the model; do not build a placeholder.

- [ ] **07.3 — Default shopping list service**
  `get_or_create_default_shopping_list`, race-safe.
  *Files:* `lists/services.py`
  *Done when:* concurrent calls still yield exactly one default list.

- [ ] **07.4 — Add-to-list services**
  `add_dish_to_list`, `add_recipe_to_list`, with visibility checks.
  *Files:* `lists/services.py`

- [ ] **07.5 — `populate_shopping_list`**
  The task 08 contract: flatten, aggregate, replace-generated-only, atomic, returns a summary.
  *Files:* `lists/services.py`
  *Done when:* regenerating twice leaves the list identical and manual items untouched.
  *Provenance note (task 05 review):* `FlatLine.from_recipes` from task 05's `flatten` is the
  **full root→leaf recipe chain** for each line, not only the recipes that directly list the
  ingredient. Decide deliberately what list-item provenance should show (contributing
  dish/recipe vs. full chain) rather than assuming `from_recipes` is already the direct
  lister.

- [ ] **07.6 — Merge and clear services**
  `merge_duplicate_items`, `clear_checked`.
  *Files:* `lists/services.py`

- [ ] **07.7 — Serializers**
  `ListSerializer`, `ListItemSerializer` with per-FK visibility validation, `ShoppingResultSerializer`.
  *Files:* `lists/serializers.py`

- [ ] **07.8 — API viewset and item routes**
  CRUD, items, reorder, add-dish, clear-checked, merge-duplicates, default-shopping.
  *Files:* `lists/api.py`, `lists/urls.py`, `lists/filters.py`

- [ ] **07.9 — List index UI**
  Grouped by kind, counts, pinned default shopping list.
  *Files:* `lists/views.py`, `templates/lists/list_index.html`

- [ ] **07.10 — Shopping list detail UI**
  Aisle grouping, one-tap check via HTMX, sticky progress, quick-add, provenance, generated-vs-
  manual styling. Optimise for one-handed phone use.
  *Files:* `templates/lists/shopping_detail.html`, `_partials/_shopping_item.html`

- [ ] **07.11 — Generic list detail UI**
  Mixed item types, inline add, up/down reordering.
  *Files:* `templates/lists/list_detail.html`

- [ ] **07.12 — "Add to list" from recipe and dish pages**
  *Files:* `templates/_partials/_add_to_list.html`

- [ ] **07.13 — Regeneration warning**
  Confirm before replacing generated items when any are checked.
  *Files:* `templates/lists/_partials/_regenerate_confirm.html`

- [ ] **07.13a — Light up the "Lists" home card**
  `templates/core/_partials/_home_content.html` still renders Lists as a non-interactive
  "Coming soon." card (all five were task-02 placeholders; 04-06 wired up their own on the way
  through). Turn it into an `<a class="card card-link" href="/lists/">` with a one-line
  description, matching the recipes/dishes/books cards. Update `core/tests/test_templates.py`
  `test_home_dashboard_cards` (the "Coming soon." count drops to 1). The richer dashboard is
  task 12 — this is just the card.
  *Files:* `templates/core/_partials/_home_content.html`, `core/tests/test_templates.py`

- [ ] **07.14 — Update the living document**
  Task 07 → AWAITING APPROVAL. Record the read-only-when-shared decision.
  *Files:* `Plan/MILESTONES.md`
