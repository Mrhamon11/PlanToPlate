# 04 — Units & Ingredients · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Follow `core/README.md` from task 03 when wiring `Ingredient` as an owned model.

- [x] **04.1 — `Unit` model and `Dimension`**
  Model, migration, admin registration.
  *Files:* `catalog/models.py`, `catalog/admin.py`
  *Done when:* migrations apply and units are visible in the admin.

- [x] **04.2 — `Tag` model**
  With `kind` and an auto-slug.
  *Files:* `catalog/models.py`

- [x] **04.3 — Unit conversion service**
  `convert`, `to_base`, `humanize`, plus the `IncompatibleUnits` exception.
  *Files:* `catalog/services/units.py`, `catalog/exceptions.py`
  *Done when:* the full conversion test matrix passes, including every refusal case.

- [x] **04.4 — `Ingredient` model**
  `OwnedModel` subclass with the fields, validators, and case-insensitive unique constraints.
  An ingredient has no owned children: per `core/README.md` and MILESTONES.md decision D33 it
  declares `contains_owned_children = False` (the greppable leaf opt-out) rather than a no-op
  `share_dependencies()`/`copy_children()` override — the task 03 convention test is satisfied
  either way, and the opt-out is what keeps it satisfied once task 05's `RecipeComponent` lands.
  *Files:* `catalog/models.py`

- [x] **04.5 — Seed fixtures and command**
  ~30 units, ~35 tags, ~150 ingredients as `is_system=True`. `manage.py seed_catalog`,
  idempotent, never touching user-owned rows.
  *Files:* `catalog/fixtures/*.json`, `catalog/management/commands/seed_catalog.py`
  *Done when:* running it twice leaves the row count unchanged.

- [x] **04.6 — Serializers**
  `UnitSerializer`, `TagSerializer`, `IngredientSerializer` (on `OwnedSerializer`),
  `ConversionRequestSerializer` (bounded `DecimalField` → 400 not 500 for oversized quantity,
  carried finding #4; `ingredient` field scoped to `visible_to`).
  *Files:* `catalog/serializers.py`

- [x] **04.7 — API viewsets**
  Read-only units and tags (staff writes via `StaffWriteReadOnly`), full ingredient viewset via
  `OwnedViewSetMixin`, `POST /api/units/convert/` as a `detail=False` action, `IngredientFilter`
  (`search`/`tags`/`is_staple`, composed on top of `visible_to`; `?mine=` from
  `core/filters.py`). `catalog/api.py`, `catalog/filters.py`, `catalog/api_urls.py` (+ HTML
  `catalog/urls.py`), wired into `config/urls.py`.
  *Done when:* every route appears in `/api/docs/` and the IDOR matrix passes. ✓

- [x] **04.8 — Protected-delete handling**
  `core/exceptions.py`: `Conflict` + `conflict_from_protected_error`. `IngredientViewSet
  .perform_destroy` and `IngredientDeleteView.form_valid` translate `ProtectedError` → 409 /
  flash. **Real end-to-end `test_delete_in_use_returns_409` deferred to task 05** (nothing
  PROTECTs `Ingredient` until `RecipeComponent`); covered here by a synthetic `ProtectedError`
  unit test + a monkeypatched viewset test.

- [x] **04.9 — Ingredient list UI**
  `IngredientListView` (debounced htmx search `keyup changed delay:300ms`, tag chips, staple
  toggle, pagination preserving the query string, empty state, ownership badges). Filters
  narrow `super().get_queryset()` (= `visible_to`), never replace it.
  *Files:* `catalog/views.py`, `templates/catalog/ingredient_list.html`, `_partials/_ingredient_results.html`

- [x] **04.10 — Ingredient detail and form**
  Detail + create/edit/delete. Share wired via an HTML intermediary (`IngredientShareModalView`
  renders task 03's `_share_modal.html`; `IngredientShareView`/`IngredientUnshareView` call
  `core.services.sharing`), copy via `IngredientCopyView` → `copy_object`, `_copied_from.html`
  on the detail page.
  *Files:* `templates/catalog/ingredient_form.html`, `ingredient_detail.html`, `ingredient_confirm_delete.html`, `ingredient_share.html`

- [x] **04.11 — Shared unit picker partial**
  `templates/_partials/_unit_select.html`, `{% regroup %}` by dimension, optional/required
  blank-option handling. Consumed by `ingredient_form.html`.

- [x] **04.12 — Quick-add ingredient endpoint**
  `IngredientQuickAddView` (POST, minimal payload, idempotent on name) → `_ingredient_row.html`
  fragment carrying the task-05 data-attribute contract.
  *Files:* `catalog/views.py`, `templates/catalog/_partials/_ingredient_row.html`

- [x] **04.13 — Update the living document**
  MILESTONES.md task 04 note updated to name 04.12 as last completed subtask (status left
  IN PROGRESS — the orchestrator flips it after human approval).
  *Files:* `Plan/MILESTONES.md`
