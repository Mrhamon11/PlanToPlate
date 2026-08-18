# 04 — Units & Ingredients · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Follow `core/README.md` from task 03 when wiring `Ingredient` as an owned model.

- [ ] **04.1 — `Unit` model and `Dimension`**
  Model, migration, admin registration.
  *Files:* `catalog/models.py`, `catalog/admin.py`
  *Done when:* migrations apply and units are visible in the admin.

- [ ] **04.2 — `Tag` model**
  With `kind` and an auto-slug.
  *Files:* `catalog/models.py`

- [ ] **04.3 — Unit conversion service**
  `convert`, `to_base`, `humanize`, plus the `IncompatibleUnits` exception.
  *Files:* `catalog/services/units.py`, `catalog/exceptions.py`
  *Done when:* the full conversion test matrix passes, including every refusal case.

- [ ] **04.4 — `Ingredient` model**
  `OwnedModel` subclass with the fields, validators, and case-insensitive unique constraints.
  Implement the `share_dependencies()` and `copy_children()` hooks (both trivial — an
  ingredient has no owned children — but required by the task 03 convention test).
  *Files:* `catalog/models.py`

- [ ] **04.5 — Seed fixtures and command**
  ~30 units, ~35 tags, ~150 ingredients as `is_system=True`. `manage.py seed_catalog`,
  idempotent, never touching user-owned rows.
  *Files:* `catalog/fixtures/*.json`, `catalog/management/commands/seed_catalog.py`
  *Done when:* running it twice leaves the row count unchanged.

- [ ] **04.6 — Serializers**
  `UnitSerializer`, `TagSerializer`, `IngredientSerializer` (on `OwnedSerializer`),
  `ConversionRequestSerializer`.
  *Files:* `catalog/serializers.py`

- [ ] **04.7 — API viewsets**
  Read-only units and tags (staff writes), full ingredient viewset via `OwnedViewSetMixin`,
  the conversion endpoint, filters and search.
  *Files:* `catalog/api.py`, `catalog/filters.py`, `catalog/urls.py`
  *Done when:* every route appears in `/api/docs/` and the IDOR matrix passes.

- [ ] **04.8 — Protected-delete handling**
  Translate `ProtectedError` into a 409 naming the recipes that block the delete.
  *Files:* `catalog/api.py`, `core/exceptions.py`

- [ ] **04.9 — Ingredient list UI**
  Debounced search, tag chips, staple filter, ownership badges, pagination, empty state.
  *Files:* `catalog/views.py`, `templates/catalog/ingredient_list.html`, `_partials/`

- [ ] **04.10 — Ingredient detail and form**
  Create/edit/delete with the share modal and copy button from task 03.
  *Files:* `templates/catalog/ingredient_form.html`, `ingredient_detail.html`

- [ ] **04.11 — Shared unit picker partial**
  `_unit_select.html`, grouped by dimension, for reuse across the app.
  *Files:* `templates/_partials/_unit_select.html`

- [ ] **04.12 — Quick-add ingredient endpoint**
  Minimal-payload create returning a row fragment, for the task 05 recipe editor.
  *Files:* `catalog/views.py`, `templates/catalog/_partials/_ingredient_row.html`

- [ ] **04.13 — Update the living document**
  Task 04 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
