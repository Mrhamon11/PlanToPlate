# 07 — Lists & Shopping · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **07.1 — `List` model**
  `OwnedModel` subclass with `kind`, the default-shopping-list flag, and the filtered unique
  constraint. Task 03 hooks.
  *Files:* `lists/models.py`

- [x] **07.2 — `ListItem` model**
  The four content FKs, quantity/unit, `source`, `generated_from`, and the has-content check
  constraint.
  *Files:* `lists/models.py`
  *Done when:* an item with no content of any kind is rejected by the database.

  > **Resolved (iteration 1):** a lazy `"planner.MealPlan"` string reference with *no* model
  > is not achievable — Django's system checks (`fields.E300`/`E307`) reject an FK to a
  > non-existent model, so `manage.py check` and the whole suite stay red, and
  > `test_regeneration_scoped_to_source_plan` has no `MealPlan` to instantiate. A **minimal
  > real stub** was added: `planner/models.py::MealPlan(OwnedModel)` — one `name` field,
  > `Meta(OwnedModel.Meta)`, `contains_owned_children = False`, plus
  > `planner/migrations/0001_initial.py`. Its docstring says loudly that **task 08 must flesh
  > it out** (`start_date`, `days`, `profile`, `profile_snapshot`, `seed`, `shopping_list`,
  > `MealPlanProfile`, `MealPlanEntry`, the generator) and **re-decide
  > `contains_owned_children` / the sharing cascade** once it gains `entries` / `shopping_list`.

- [x] **07.3 — Default shopping list service**
  `get_or_create_default_shopping_list`, race-safe.
  *Files:* `lists/services.py`
  *Done when:* concurrent calls still yield exactly one default list.

- [x] **07.4 — Add-to-list services**
  `add_dish_to_list`, `add_recipe_to_list`, with visibility checks.
  *Files:* `lists/services.py`

- [x] **07.5 — `populate_shopping_list`**
  The task 08 contract: flatten, aggregate, replace-generated-only, atomic, returns a summary.
  *Files:* `lists/services.py`
  *Done when:* regenerating twice leaves the list identical and manual items untouched.
  *Provenance note (task 05 review):* `FlatLine.from_recipes` from task 05's `flatten` is the
  **full root→leaf recipe chain** for each line, not only the recipes that directly list the
  ingredient. Decide deliberately what list-item provenance should show (contributing
  dish/recipe vs. full chain) rather than assuming `from_recipes` is already the direct
  lister.

  > **Decided (iteration 1):** the full chain is **not** persisted. A `GENERATED` `ListItem`
  > records its contributing **dish** on `ListItem.dish` — but only when exactly one dish fed
  > that aggregated ingredient line. When several dishes share an ingredient, `dish` is left
  > null and `generated_from` (the plan) is the provenance. Rationale: at the shopping-list
  > layer the useful "why is this here" is "which dinner", not the sub-recipe nesting path,
  > and `ListItem` has a single `dish` FK slot. Documented in `lists/services.py`'s module
  > docstring. `_merge_generated_lines` applies the same rule — it nulls `dish` when a second,
  > different dish merges into an existing single-dish line.

- [x] **07.6 — Merge and clear services**
  `merge_duplicate_items`, `clear_checked`.
  *Files:* `lists/services.py`

- [x] **07.7 — Serializers**
  `ListSerializer`, `ListItemSerializer` with per-FK visibility validation, `ShoppingResultSerializer`.
  *Files:* `lists/serializers.py`

- [x] **07.8 — API viewset and item routes**
  CRUD, items, reorder, add-dish, clear-checked, merge-duplicates, default-shopping.
  *Files:* `lists/api.py`, `lists/urls.py`, `lists/filters.py`

---

### Carry-over from the 07.1–07.8 review (do these in the continuation run)

The backend slice (07.1–07.8) passed tester + reviewer and is **APPROVED but uncommitted** on
`task/07-lists-and-shopping`. Two review follow-ups were accepted for this run rather than
blocking the slice:

- [x] **CO-1 — Enforce exactly one content FK in `ListItemSerializer.validate`.**
  Today `validate` only checks *has-content*, so `POST /api/lists/<id>/items/`
  `{"recipe": R, "dish": D}` with no `text` is accepted. If R and D are collected in the
  *same* deletion pass (e.g. admin "delete selected" over a user owning both, item on another
  user's list), each `pre_delete` receiver skips the item because the *other* FK is still set,
  then both FKs null → `lists_listitem_has_content` violated → delete transaction 500s. The
  `ListItem` docstring already says "exactly one of…" and every service already produces
  single-FK items, so this only tightens the serializer to match. ~5 lines + a test.
  *Files:* `lists/serializers.py`, `lists/tests/test_security.py` (or `test_api.py`)

- [x] **CO-2 — Add a queryset/cascade tombstone test.**
  Every current deletion test uses `instance.delete()`. Add a
  `Recipe.objects.filter(pk__in=[...]).delete()` case asserting the tombstone `text` still
  lands — guards against a silent `can_fast_delete` regression in a future Django.
  *Files:* `lists/tests/test_models.py`

- [x] **CO-3 — One-line comment on the app-wide `pre_delete` side effect** in `lists/signals.py`:
  registering these receivers disables `can_fast_delete` for Recipe/Dish/Ingredient
  everywhere and fires a filtered no-op `UPDATE` on every such delete. Immaterial at 10–20
  users; note it so a future bulk-cleanup author isn't surprised.
  *Files:* `lists/signals.py`

**Deferred to task 08** (need the real planner caller — do *not* action in task 07):

- Finding 3 — `populate_shopping_list` reimplements dish flattening inline and, unlike
  `add_dish_to_list`, does not pass `viewer` through to filter component recipes by
  `.visible_to()`. Harmless now (`actor = lst.owner`, no API surface); reconcile when task 08
  wires the real caller with a distinct actor.
- Finding 7 — the `(ingredient_id, unit_id)` merge key in `add_dish_to_list` is unstable under
  friendly-unit promotion, so two calls can split one ingredient across two lines. Minor,
  recoverable via `merge-duplicates`; proper fix is to normalise to base units for the upsert
  key, best done alongside the task-08 work.

Minor, no action needed: `reorder_items` silently ignores duplicate ids in the payload (Case
takes the first match — quiet, not a crash).

### Post-approval review follow-ups (non-blocking, actioned)

Task 07 was APPROVED; these five reviewer notes were then actioned in a follow-up pass:

1. `AddToListView` — `.isdigit()` guard on the `list` POST value (a non-numeric value used to
   500). Test in `test_views.py`.
2. `ARCHITECTURE.md` D41 — deferral extended to name **task 09** (admin user-delete, `owner`
   `CASCADE`, is the realistic trigger for the two-FK tombstone blind spot); cross-reference
   note added to `Plan/09-Admin-Control-Center/design.md`.
3. `move_item` — service + view reorder tests added (`test_items.py`, `test_views.py`),
   including the boundary no-ops.
4. No-JS `?page=N` loss — `ListItemCheckView` / `ListItemAddView` now preserve `page` via a
   hidden form field and `_list_redirect` helper.
5. Stale comments in `planner/models.py` (system-check `fields.E300`/`E307`, not
   `makemigrations`) and `lists/models.py:133` (stub exists) corrected.

---

- [x] **07.9 — List index UI**
  Grouped by kind, counts, pinned default shopping list.
  *Files:* `lists/views.py`, `templates/lists/list_index.html`

- [x] **07.10 — Shopping list detail UI**
  Aisle grouping, one-tap check via HTMX, sticky progress, quick-add, provenance, generated-vs-
  manual styling. Optimise for one-handed phone use.
  *Files:* `templates/lists/shopping_detail.html`, `_partials/_shopping_item.html`

- [x] **07.11 — Generic list detail UI**
  Mixed item types, inline add, up/down reordering.
  *Files:* `templates/lists/list_detail.html`

- [x] **07.12 — "Add to list" from recipe and dish pages**
  *Files:* `templates/_partials/_add_to_list.html`

- [x] **07.13 — Regeneration warning**
  Confirm before replacing generated items when any are checked.
  *Files:* `templates/lists/_partials/_regenerate_confirm.html`

- [x] **07.13a — Light up the "Lists" home card**
  `templates/core/_partials/_home_content.html` still renders Lists as a non-interactive
  "Coming soon." card (all five were task-02 placeholders; 04-06 wired up their own on the way
  through). Turn it into an `<a class="card card-link" href="/lists/">` with a one-line
  description, matching the recipes/dishes/books cards. Update `core/tests/test_templates.py`
  `test_home_dashboard_cards` (the "Coming soon." count drops to 1). The richer dashboard is
  task 12 — this is just the card.
  *Files:* `templates/core/_partials/_home_content.html`, `core/tests/test_templates.py`

- [x] **07.14 — Update the living document**
  Task 07 → AWAITING APPROVAL. Record the read-only-when-shared decision.
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`

  > **MILESTONES.md row** (rewrite the current `IN PROGRESS` stub as a 2–3 line summary):
  > `List` / `ListItem` (four nullable content FKs, has-content check, `SET_NULL` +
  > `pre_delete` tombstone receiver), `lists/services.py` (race-safe default list,
  > add-to-list, `populate_shopping_list` = the task-08 contract, merge/clear), serializers +
  > REST API, HTMX UI. Still open: a minimal `planner.MealPlan` stub was added that **task 08
  > must flesh out**; CO-1 (exactly-one-content-FK serializer guard) if not done this run;
  > findings 3 & 7 deferred to task 08.
  >
  > **ARCHITECTURE.md decision log** — add entries for:
  > 1. **Read-only when shared.** A shared `List` is read-only for the recipient; they cannot
  >    check items off. Collaborative editing is out of scope (task 03 grants read, not write).
  > 2. **Tombstone `pre_delete` receiver** (`lists/signals.py`). The `lists_listitem_has_content`
  >    check constraint and `SET_NULL` on the content FKs collide for a content-only item; a
  >    `pre_delete` receiver on Recipe/Dish/Ingredient stamps fallback `"(deleted …)"` text
  >    before the FK is nulled. Side effect: `can_fast_delete` is disabled for those three
  >    models app-wide.
  > 3. **No dish-level dedupe in `populate_shopping_list`.** A dish scheduled twice in a plan
  >    aggregates to 2× — a repeated dinner needs double the groceries.
  > 4. **List-item provenance = contributing dish, single-contributor only** (see 07.5 note).
  > 5. **`planner.MealPlan` minimal stub** introduced by task 07 for the `generated_from` FK;
  >    task 08 owns its real shape and must re-decide its `contains_owned_children` /
  >    sharing-cascade posture.

---

### Dev-test fixes (2026-09-05) — continuation run, before final approval

From a manual dev-test pass over the shipped UI. Bugs + two small feature gaps that must work
before task 07 is signed off; the larger UX additions the same pass surfaced went to task 11
(11.22–11.27) and task 13 (editable sharing).

- [x] **07.15 — `×` remove button on a shopping row 403s**
  `shopping_detail.html` includes `_shopping_item.html` with `{% include … only %}` (needed so
  the OOB progress element doesn't render once per row). `only` also strips `csrf_token`, so
  the native remove `<form>` renders with **no `csrfmiddlewaretoken` field** → browser POST
  fails Django's CSRF check → 403. The check button dodges it only because htmx sends the token
  as a header. Fix: pass `csrf_token` explicitly into the include. Add a test that renders the
  page and POSTs the remove form with CSRF enforced (the missing coverage that let this ship).
  *Files:* `templates/lists/shopping_detail.html`, `lists/tests/test_views.py`

- [x] **07.16 — Generic-list add form falls through to free text**
  In `ListItemAddView`, picking "Recipe" or "Dish" but leaving that dropdown empty while the
  text box has content adds a *free-text* item instead of erroring — the view only honours the
  selected kind when a valid id is present. Fix: when `kind` is explicitly `recipe`/`dish`,
  require that reference and error otherwise; only `kind == "text"` reads the text box.
  *Files:* `lists/views.py`, `lists/tests/test_views.py`

- [x] **07.17 — Stale "from the meal plan" provenance label**
  A generated line with no single contributing dish (two dishes merged into one aisle line, or
  the one dish since deleted) falls back to the literal text "from the meal plan" — wrong in
  task 07, where no meal plan exists. Fix `annotate_display` / the template: show "from
  &lt;Dish&gt;" only when a dish is set and visible; show "from the meal plan" only when
  `generated_from` is actually set; otherwise render **no** provenance line (the
  generated-vs-manual styling already marks the row). Covers dev-test findings 5d and 8.
  *Files:* `lists/services.py`, `templates/lists/_partials/_shopping_item.html`,
  `templates/lists/list_detail.html`, `lists/tests/test_views.py`

- [x] **07.18 — `<details>` menus and typeahead dropdowns don't close on outside click**
  App-wide (finding 5b): `<details class="nav-menu">` (nav menus, "Add to list ▾", "Add to
  book ▾") and the `recipe-editor.js` `.component-results` typeahead lists stay open until
  re-clicked, and opening one leaves others open. Add a small shared script: close open
  `nav-menu` disclosures and typeahead result lists on outside-click and Escape; close other
  open disclosures when one opens. Keep no-JS behaviour intact.
  *Files:* a new `static/js/menus.js` (or fold into an existing bundle) + `base.html`;
  `static/js/recipe-editor.js`. Tracked app-wide as [[11.25]].

  > **Done:** new `static/js/menus.js` (loaded from `base.html` after alpine, `defer`). On a
  > document click outside an open `details.nav-menu` it closes it; on `toggle` it closes any
  > other open one (capture-phase listener — `toggle` does not bubble); Escape closes the open
  > one and restores focus to its `<summary>`. For the typeahead it empties every
  > `.component-results` not inside the clicked `.component-picker` (Escape empties all) —
  > `recipe-editor.js` still owns clearing on a pick, so it was not modified. No transitions
  > added, so `prefers-reduced-motion` needs nothing. Native `<details>` still toggles with no
  > JS. **Addresses app-wide bug-fix item 11.25.**

- [x] **07.19 — Shopping list: separate "Check all" and "Clear all" buttons**
  Findings Note 1 + 4. Add two controls to the shopping detail, **distinct from** the existing
  "Clear checked (N)":
  - **Check all** — mark every item on the list checked (one action).
  - **Clear all** — delete every item on the list, behind a confirm dialog (destructive).
  Two thin services (`check_all` / `clear_all`, or `set_all_checked`), owner-only like the rest.
  *Files:* `lists/services.py`, `lists/views.py`, `lists/urls.py`,
  `templates/lists/shopping_detail.html`, a confirm partial, `lists/tests/test_*.py`

---

### Dev-test round 2 (2026-09-05) — continuation, before final approval

- [x] **07.20 — "Check all" toggles to "Uncheck all"**
  When every item on a shopping list is already checked, the button reads **"Uncheck all"** and
  unchecks them all; otherwise it reads "Check all". `set_all_checked` already takes
  `is_checked`; add the uncheck route/branch and the template's toggle logic (the view already
  computes `progress.checked` / `progress.total`).
  *Files:* `lists/views.py`, `lists/urls.py`, `templates/lists/shopping_detail.html`,
  `lists/tests/test_views.py`

- [x] **07.21 — Remove the "from …" provenance label from the list UI**
  Dev-test decision: the label carries no weight in task 07's hand-add flow. **Keep** the
  `ListItem.dish` provenance *data* and the `_merge_generated_lines` / `populate_shopping_list`
  single-contributor rule (task 08 needs it) — just stop rendering any "from ‹Dish›" /
  "from the meal plan" caption in `_shopping_item.html` and `list_detail.html`. Drop
  `provenance_label` (or leave it computed but unused — prefer removing it and the template
  branch). Rename `test_provenance_shown_on_generated_items` →
  `test_generated_item_records_dish_but_shows_no_label` (assert `ListItem.dish` is set, assert
  no "from" text in the HTML). `design.md` "Provenance" bullet and `test-plan.md` already
  updated. Task 08 owns bringing a provenance display back.
  *Files:* `lists/services.py`, `templates/lists/_partials/_shopping_item.html`,
  `templates/lists/list_detail.html`, `lists/tests/test_views.py`

- [x] **07.22 — "Clear all" on the generic list detail too**
  Reviewer NB4: 07.19 scoped the bulk buttons to the shopping detail; the generic list detail
  offers "Delete list" but no "Clear all". Add the same "Clear all" (reusing `clear_all` +
  the confirm templates) to `list_detail.html`.
  *Files:* `lists/views.py` (reuse the existing clear-all views — they already work for any
  kind), `templates/lists/list_detail.html`, `lists/tests/test_views.py`

- [x] **07.23 — Inline edit of an item's quantity and unit** (was 11.23)
  An aggregated shopping line ("2 cups chicken breast") is often not a buyable amount. The user
  must be able to override `quantity` and `unit` on any list item to whatever they'll actually
  buy — the program assumes nothing.
  - **UI:** a small inline edit on each shopping row (and each generic-list row that carries a
    quantity) — a number input for `quantity` + `_partials/_unit_select.html` for `unit`, HTMX
    partial swap on save, no-JS fallback (a plain form that reloads). Owner-only, like every
    other list mutation.
  - **Service:** a thin `lists/services.py::update_item(item, *, quantity, unit) -> ListItem`
    (type-hinted, `Decimal` quantity). Validate: `unit` must be `visible_to` the actor
    (staff-writable system units are always visible); a `unit` set with no `quantity` is
    rejected; `quantity` may be cleared to null (a bare "chicken breast" line). Keep the REST
    path (`ListItemSerializer` `PATCH`) and this HTML path on the same rule — route the
    serializer's `update` through `update_item` too if practical.
  - **`source` / regeneration:** editing a `GENERATED` line's quantity does **not** change its
    `source`. Document (in the service docstring and `design.md` "Edge cases", next to the
    checked-state-loss note) that a future `populate_shopping_list` regeneration (task 08) will
    overwrite a manual quantity edit to a generated line — same accepted trade-off as checked
    state. "My override survives regeneration" is a task 08 decision, not this.
  - **Tests:** owner edits quantity+unit and it persists and re-renders; non-owner → 403;
    unit-without-quantity rejected; quantity cleared to null allowed; a `GENERATED` line stays
    `GENERATED` after an edit; an **unknown** unit id is rejected (a real `Unit` is required) —
    a valid unit is never rejected for dimensional incompatibility (`design.md` "Edge cases":
    the app assumes nothing); a non-finite / negative / over-long `quantity` is rejected on
    both surfaces (error + 302 on HTML, 400 on REST) with the DB unchanged.
  *Files:* `lists/services.py`, `lists/serializers.py`, `lists/views.py`, `lists/urls.py`,
  `templates/lists/_partials/_shopping_item.html`, `templates/lists/list_detail.html`,
  a small `_item_qty_edit.html` partial, `lists/tests/test_items.py`,
  `lists/tests/test_views.py`, `lists/tests/test_api.py`

- [x] **07.24 — Shopping-list action bar doesn't refresh after a one-tap check**
  Dev-test finding (2026-09-06): the `detail-actions` bar (Check all / Uncheck all,
  **Clear checked (N)**, Clear all, Clear generated) is only rendered on a full page load. A
  one-tap HTMX check swaps the row and the sticky progress counter OOB but leaves the action
  bar stale — so "Clear checked (N)" never appears until you reload or use "Check all" (which
  does a full redirect), and "Check all" doesn't flip to "Uncheck all" on the last tick.
  Fix: extract the `detail-actions` block into `_partials/_shopping_actions.html` with a stable
  id (`#shopping-actions`), include it from `shopping_detail.html`, and have the check-toggle
  fragment (`_shopping_item.html`'s trailing OOB section, alongside `_shopping_progress.html`)
  re-render it with `hx-swap-oob="true"` — inert on first load, same as the progress partial.
  `_render_shopping_item` must supply the partial's context (`progress`, `has_generated` via a
  cheap `lst.items.filter(source=GENERATED).exists()`, `list`, `is_owner`, `csrf_token`).
  Test: a one-tap check response contains the "Clear checked (1)" button markup OOB; unchecking
  the last checked item drops it again; checking the last unchecked item flips "Check all" →
  "Uncheck all" in the fragment.
  *Files:* `templates/lists/shopping_detail.html`,
  `templates/lists/_partials/_shopping_item.html`,
  `templates/lists/_partials/_shopping_actions.html` (new), `lists/views.py`,
  `lists/tests/test_views.py`
