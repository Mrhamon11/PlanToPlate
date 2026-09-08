# 11 — Task Bug Fixes · Subtasks

> Living doc: [`../MILESTONES.md`](../MILESTONES.md)

A standing catch-all task, established 2026-08-25 out of task 03's review. Not every finding
from a p2p-reviewer pass is worth fixing (or even fully designing) the moment it's found — some
are real but low-priority: no user impact at this project's scale, or better addressed once a
task exists that actually exercises the code path. Rather than lose those, they get recorded
here as a subtask each, with just enough detail to pick back up later.

**Going forward:** when a review finds something genuinely deferrable — not blocking, not worth
interrupting the current task for — add it here as a new subtask instead of letting it evaporate
in a chat transcript. `design.md` and `test-plan.md` for this task are deliberately not written
yet; write the relevant slice of each (or a per-subtask note, if the fix is small enough not to
need a full design) only when a subtask is actually picked up.

- [ ] **11.1 — Copy depth-cap is order-dependent relative to the memoization check**
  *Found in:* task 03 review (NB2), `core/services/copying.py`.
  *Issue:* `Copier`'s depth-cap check runs after the memo-hit check, so on a graph with both a
  diamond dependency and a long chain, whether `copy_object` raises `DepthExceededError` depends
  on pk/edge insertion order — and it can disagree with what `walk_dependencies` (the sharing
  cascade's helper) would conclude on the *identical* graph. Recursion still stays bounded
  overall via `MAX_NODES`, so this is not a safety defect, but it's untested in either direction
  and disagrees with `design.md`'s claim that copy "shares the recipe traversal helper" for
  depth-capping. Needs a decision on a single canonical depth-counting rule shared by both
  services, then a test pinning it.

- [ ] **11.2 — N+1 query pattern in the sharing/copy cascade validators**
  *Found in:* task 03 review (NB6), `core/services/sharing.py` (`_validate_cascade`,
  `_validate_public_cascade`) and `core/services/copying.py`.
  *Issue:* Both validators call `.visible_to(user)` inside a loop over dependencies (and, for
  per-user sharing, a nested loop over target users), one query per iteration rather than a
  single batched query. Acceptable at this project's scale (`MAX_NODES` capped at 1000,
  10-20 users total) but would benefit from batching if either cap grows.

- [ ] **11.5 — Unprefetched graph walk in recipe DAG traversal helpers**
  *Found in:* task 05 review (NB4), `recipes/services/graph.py`.
  *Issue:* `assert_no_cycle` / `recipe_depth` / `_find_chain` walk `.components` and
  `.used_in` without prefetch — one query per node visited. Bounded and harmless at the
  depth-5 / cycle-guard limits enforced today. Revisit if a bulk recipe import path lands
  that runs these over many recipes at once; batch with `prefetch_related` then.

- [ ] **11.3 — `OwnedSerializer`'s declared-field assertion trap for subclasses**
  *Found in:* task 03 review (NB7), `core/serializers.py`.
  *Issue:* `OwnedSerializer` declares `owner`, `is_system`, `shared_with`, `copied_from`, and
  `visibility` directly (not via `read_only_fields`), so a subclass that lists a `Meta.fields`
  omitting one of them hits a DRF assertion error at import/first-use time rather than a clear
  message pointing at the cause. Document the requirement (every subclass's `Meta.fields` must
  include all five) in `core/README.md` (03.11) when that file is written, and/or add a
  `django.core.checks` system check mirroring the existing owner-manager check in
  `core/apps.py`.

- [ ] **11.6 — `mark_made` increment is a Python read-modify-write, not `F()`**
  *Found in:* task 05 review (NB1), `recipes/services/stats.py`.
  *Issue:* `stats.times_made += 1` reads the value into Python and writes it back, so two
  concurrent `mark_made` calls for the same (user, recipe) can lose an increment. Masked today
  because SQLite runs with `transaction_mode="IMMEDIATE"` and serialises writers, but it would
  be a genuine lost update on Postgres (the documented portability target). Fix with
  `RecipeStats.objects.filter(...).update(times_made=F("times_made") + 1, last_made_at=...)`
  or an `F()` expression on the instance.

- [ ] **11.7 — DAG traversal error messages are inconsistent (PKs vs names)**
  *Found in:* task 05 review (NB3), `recipes/services/graph.py`.
  *Issue:* `recipe_depth` / `_depth_above` raise `CycleError` with stringified PKs, while the
  chains in `assert_no_cycle` and `_flatten_into` use recipe names. A pre-existing cyclic row
  is unfixable by the user regardless, so this is cosmetic — align the message format when the
  file is next touched.

- [ ] **11.8 — `_has_component_graph` sentinel is too weak**
  *Found in:* task 05 review (NB4, this round), `recipes/services/flatten.py`.
  *Issue:* `_has_component_graph` only checks for the `"components"` prefetch cache key. A
  caller doing a shallow `Recipe.objects.prefetch_related("components").get()` passes the check
  and then hits silent per-sub-recipe N+1 during recursion. Only `flatten` consumes this and
  only tasks 07/08 (not yet built) call it, so latent. Replace the docstring reliance with a
  stronger sentinel or an assertion that the full `MAX_DEPTH + 1` prefetch chain is present.

- [ ] **11.4 — No reusable mechanism for the relation-leakage security rule**
  *Found in:* task 03 review (NB8), `design.md`'s security note #4 ("leakage through
  relations").
  *Issue:* Nested serializers filtering their children through `.visible_to()` is currently ad
  hoc — done correctly in the one place task 03 tests it (`test_nested_children_filtered_by_visibility`),
  but nothing stops a task 04-08 model's serializer from expanding a nested relation without the
  filter. Consider a reusable `VisibleRelatedField` (or equivalent) serializer field, plus a
  convention test (alongside 03.8a/NB3's `test_conventions.py`) asserting every nested relation
  on an `OwnedModel` serializer routes through it.

- [ ] **11.9 — Combined sub-recipe depth is not pre-checked on a multi-component write**
  *Found in:* task 05 review (NB2), `recipes/services/graph.py` (`assert_no_cycle`),
  `recipes/serializers.py` (`_write_components`), `recipes/services/components.py`
  (`assert_drafts_acyclic`).
  *Issue:* the cycle/depth guard runs **per component**, so a single write adding two
  individually-legal sub-recipes whose subtrees are jointly deeper than `MAX_DEPTH` slips past
  the pre-check. Not a safety defect — `flatten` still raises `DepthExceededError` at runtime,
  so `/flattened/` degrades to a clean 400 rather than hanging — but the write is accepted when
  it should be rejected up front. Fix by checking the combined post-write depth of the whole
  draft set (compute `recipe_depth` over the proposed graph once, not edge-by-edge) and add a
  test on both the serializer and the form write paths.

- [ ] **11.10 — Recipe form yield-unit default is `each`, not the `serving` design specifies**
  *Found in:* task 05 review (NB4), `recipes/views.py` (`_default_yield_unit`).
  *Issue:* `design.md` specifies a "4 serving" default on the new-recipe form; the seeded
  catalog has no `serving` unit, so the form falls back to `each`. Recorded as a deviation in
  the task 05 MILESTONES row. Resolve by adding a `serving` unit (COUNT dimension, `generic`
  family) to `catalog/management/commands/seed_catalog.py` / `catalog/fixtures/units.json` —
  a catalog-fixture change — then point `_default_yield_unit` at it and drop the fallback
  comment. `Plan/09-Admin-Control-Center/design.md`'s example payload already assumes
  `"yield_unit": "serving"` exists.

- [ ] **11.11 — Revoking a share / narrowing visibility does not cascade down the object graph**
  *Found in:* task 05 dev test, `core/services/sharing.py` (`unshare`, and the visibility-down
  path in `share` / `set_visibility`); re-confirmed task 12 dev test, 2026-09-07.
  *Issue:* granting access cascades **down** the owned-object graph — sharing or publishing a
  container pulls in every dependency the actor owns — but **revoking does not** (the deliberate
  asymmetry logged as D31). This applies on every cascade path, not just recipe → sub-recipe:
  - **Recipe → sub-recipe** — unshare / privatise a super-recipe, its sub-recipes stay granted.
  - **Dish → component recipes → sub-recipes** — a dish reverted from `PUBLIC`/shared leaves its
    recipes granted.
  - **RecipeBook → entry recipes** — same.
  - **MealPlan → scheduled dishes → recipe graphs** (D47) — same.

  *Concrete incident (task 12 dev test):* `avi`'s two demo dishes were `PUBLIC` at seed time;
  `_cascade_grant_public` flipped their five component recipes to `PUBLIC`. The dishes were
  later reverted to `PRIVATE`/`SHARED`; the recipes stayed `PUBLIC` and so were visible on a
  brand-new account's dashboard ("Public from others" + section counts). The dashboard was
  correct — `visible_to` faithfully returns `PUBLIC` rows to every account — the strand is here.

  *Why not a blind reverse-cascade:* a dependency may still back **another** container that is
  legitimately shared/public. The fix needs the reachability computation ("which of these
  children are not reachable from any other still-shared/public root") plus a small confirm UI
  ("also revoke access to these: ☐ ☐", defaulting to the safe set) on every revoke/narrow path,
  and it reverses D31.

  *Scope is a task 13 decision — do not build this leg standalone first.* Task 13
  (`Plan/13-Collaborative-Sharing/design.md`) is expected to narrow per-object individual
  sharing to `Recipe` only and move households onto a group model (its carried-in findings 1–2).
  If it does, the Dish / Book / Plan → recipe legs above **disappear** — those objects become
  private-or-group-visible, and leaving a group drops all access atomically with nothing
  stranded. What survives task 13 regardless: **reverting `PUBLIC` on any still-`PUBLIC`-capable
  container does not un-publish its children** (D31). That residual is flagged as an explicit
  spec item in task 13's carried-in finding 5; resolve it there. Pick this subtask up only for
  the `Recipe`-level legs, and only after task 13's sharing model is settled.

- [ ] **11.12 — Recipe list filter panel is too cluttered; collapse it behind a disclosure**
  *Found in:* task 05 dev test, `templates/recipes/recipe_list.html`.
  *Issue:* the whole filter form (search + role + time + rating + favourites + tag chips) is
  always expanded above the results. Wanted: show only the search box with a "▸" that expands
  the rest (Alpine is already loaded; a `<details>`/`<summary>` also works). The **Clear
  filters** link (added in 05.15) stays always-visible. Keep the no-JS path working — the
  fields must still be reachable with the disclosure closed by default only when JS is on.

- [ ] **11.13 — Ingredient / sub-recipe / dish-recipe typeahead has no keyboard navigation**
  *Found in:* task 05 dev test, re-confirmed task 07 dev test (finding 4).
  `static/js/recipe-editor.js` + `_component_row.html` (recipe ingredient & sub-recipe rows)
  **and the dish form's recipe typeahead** (same `recipe-editor.js` pattern).
  *Issue:* the custom typeahead dropdown can't be driven with the arrow keys / Enter the way a
  native `<select>` can — a mouse is required to pick a result. Add ArrowUp/ArrowDown to move a
  highlight through `.component-results`, Enter to choose, Escape to dismiss, with
  `aria-activedescendant` wiring for screen readers. Escape-to-dismiss now partly exists via
  `menus.js` (07.18) — the arrow-key highlight + Enter-to-choose is what remains. Fix every
  place that renders `.component-results` in one pass.

- [ ] **11.14 — Recipe-delete blocker handling should become a small registry**
  *Found in:* task 06 review (NB3), `recipes/services/deletion.py`.
  *Issue:* the delete-blocker check now does `apps.get_model("meals", "DishComponent")` — the
  right way to dodge the `recipes` → `meals` import cycle, and documented, but it hard-codes one
  consumer. Lists (07) and the planner (08) currently use `SET_NULL` on their `Recipe` FKs so
  they add no blocker, but if any future model takes a `PROTECT` relation to `Recipe` this
  function grows another lazy lookup. Replace it with a tiny registry: each app that protects a
  `Recipe` registers a `(label, count_fn, name_fn)` blocker; the deletion service iterates the
  registry. Pick up only when a second `PROTECT`-on-`Recipe` consumer actually lands.

- [ ] **11.15 — Book-detail "add recipe" control is an unbounded `<select>`**
  *Found in:* task 06 review (NB3, final round), `meals/views.py` (`RecipeBookDetailView`,
  ~line 503) + `templates/meals/recipebook_detail.html`.
  *Issue:* the view loads every recipe `visible_to` the requester into a Python list and renders
  it as a plain `<select>` on every book-detail render. Fine at 10-20 users, but grows without
  bound as the shared catalog does. Replace with a typeahead like the dish component form's
  (`static/js/recipe-editor.js` pattern), keeping a no-JS fallback. Sibling of [[11.12]] /
  [[11.13]] — pure UI, no correctness impact.

- [ ] **11.16 — `DishSerializer.to_representation` double-serialises components**
  *Found in:* task 06 review (NB4, final round), `meals/serializers.py` (~line 139).
  *Issue:* `to_representation` calls `super().to_representation()` (which serialises *all*
  components) and then overwrites `data["components"]` with the `visible_to`-filtered set.
  Output is correct — no leak — just wasted work on every dish render. Filter the component
  queryset before the nested serializer runs (e.g. override `get_attribute` on the field, or
  build the list directly) rather than serialising then discarding.

- [ ] **11.17 — Dish form re-render runs one query per submitted row**
  *Found in:* task 06 review (NB5, final round), `meals/views.py` (`_label_for`, ~line 262).
  *Issue:* when the dish form is re-rendered after a validation error, `_label_for` issues one
  query per submitted component row to resolve its display label. Batch the lookups into a
  single `visible_to` query keyed by recipe id. Minor — only hit on the validation-error path.

- [ ] **11.18 — Two parallel `GraphError` hierarchies; dish/recipe detail page can 500**
  *Found in:* task 06 post-approval cleanup (dev note), `core/services/graph.py` vs
  `recipes/services/graph.py`.
  *Issue:* there are two unrelated `GraphError` class hierarchies — `core.services.graph`
  (`DepthExceededError` / `CycleError`, raised by the sharing/copy cascade `walk_dependencies`)
  and `recipes.services.graph` (`DepthExceededError`, raised by `flatten`). The share views now
  catch the `core` one; nothing catches the `recipes` one on the render path. `DishDetailView`
  and the recipe detail page call `flatten(...)` in `get_context_data`, so a recipe/dish whose
  sub-tree is past the depth cap 500s the detail page. Not reachable through the app's own write
  paths today (the component service guards depth on write), so latent — but a pre-existing DB
  row or a future bulk-import path could trigger it. Fix: either unify the two hierarchies or
  guard the detail-page `flatten` call and degrade to a rendered warning. Consider a plan note
  in `ARCHITECTURE.md` about the two hierarchies regardless.

- [ ] **11.19 — A share recipient has no way to remove a shared object from their own view**
  *Found in:* task 06 dev test (notes a & b). New sharing-model surface — task 03 territory.
  *Issue:* when a recipe / dish / book is shared *with* a user, that user cannot get rid of it.
  It sits in their lists forever, and if they copy it to make it their own, they then see two
  entries with the same name (their copy plus the still-shared original — the "duplicate in the
  dish typeahead" symptom from the task 06 test).
  *Two parts:*
  (a) A recipient-initiated "remove this from my view" / "decline share" action on any
  `OwnedModel` shared with them — drops the current user from `shared_with` (or records a
  per-user hide if a shared object should stay declinable-but-not-permanently-severed). Owner
  is unaffected; a re-share restores it. Distinct from [[11.11]], which is the *owner* revoking.
  (b) On copy, offer to drop the original share in the same step ("I have my own copy now —
  stop sharing the original with me"), so the deep-copy flow doesn't leave a duplicate behind.
  *Needs:* a design slice (does declining remove the grant outright, or set a per-user
  `SharedObjectHide` row? how does it interact with a book/dish that transitively shared child
  recipes?), the service work, and both API + HTMX entry points. Write it up when picked up.

- [ ] **11.20 — Dish form and API disagree on a recipe repeated across two rows**
  *Found in:* task 06 fix-cycle review (NB2), `meals/services/dishes.py` (`parse_dish_component_drafts`,
  ~line 122).
  *Issue:* `recipe_ids` is built as a set, so two component rows referencing the same recipe give
  `len(recipe_ids) != len(rows)` and are rejected with the misleading message *"Every dish row
  must reference a recipe."* The REST path (`DishSerializer._write_components`) writes the
  duplicate rows without complaint — `DishComponent` has no unique constraint — so the two entry
  points disagree (`CLAUDE.md` §6, "never implement the same rule twice"). Decide the rule: if a
  recipe may legitimately appear twice in a dish (e.g. a sauce used at two servings), let both
  paths accept it; if not, reject it explicitly on both with an accurate message. Low impact at
  this scale.

- [ ] **11.21 — Book-detail fragment endpoints are N+1 on book size**
  *Found in:* task 06 fix-cycle review (NB3), `meals/views.py` (`_book_detail_context` /
  `_sorted_book_entries`), consumed by `BookRemoveRecipeView`, `BookEntryMoveView`,
  `BookOrderingView`.
  *Issue:* after `book.refresh_from_db()` these re-render `_book_sections.html` off
  `book.entries.all()` unprefetched, one query per entry for `entry.recipe`. Pre-existing in the
  move/ordering views (approved in the main task-06 review); the new remove view follows the
  same pattern. One fix closes all three: have `_book_detail_context` re-fetch the book with
  `prefetch_related("entries__recipe")` (or take a prefetched instance). Add a query-count test
  for the fragment endpoints. Fine at 10–20 users. Sibling of [[11.17]].

- [ ] **11.22 — Recipe added to a shopping list should expand to its ingredients**
  *Found in:* task 07 dev test (finding 5c).
  *Issue:* `add_recipe_to_list` always adds a recipe as a single reference line, on every kind
  of list — the 07.5 decision, pinned by `test_add_recipe_adds_recipe_reference_not_ingredients`.
  A user reading a recipe wants to add *all its ingredients* to a shopping list without first
  building a `Dish`. Wanted: on a `SHOPPING` list, a recipe expands to its ingredient lines
  **at the component quantities as listed — no yield scaling** (yield only scales a recipe used
  *as a sub-recipe*; a recipe added directly is `factor=1`). Sub-recipe components still flatten
  through task 05's `flatten` service. On every other kind of list it stays a reference line, as
  now. *Needs:* reverse the 07.5 decision in `Plan/07-Lists-And-Shopping/design.md`, update
  `test_add_recipe_adds_recipe_reference_not_ingredients` and the test-plan row, extend
  `add_recipe_to_list` (mirror `add_dish_to_list`'s SHOPPING branch), and wire the
  "Add to list ▾" recipe control + the generic-list add form. Provenance: record the
  contributing recipe the same single-contributor way `ListItem.dish` records a dish — needs a
  `ListItem.recipe`-as-provenance rule or accept null provenance for recipe-sourced lines.

- [x] **11.23 — No UI to edit a list item's quantity / unit after it is added**
  *Found in:* task 07 dev test (finding 5c.ii). **Pulled back into task 07 as subtask 07.23**
  (2026-09-06) — the user needs it now: an aggregated line like "2 cups chicken breast" is not
  a buyable quantity, and the shopping list is not usable without a manual override. Done in
  task 07, not here.

- [ ] **11.24 — Manual ordering for shopping lists (store-walk order)**
  *Found in:* task 07 dev test (finding 5c.ii).
  *Issue:* the shopping detail groups by aisle and sorts alphabetically within each aisle;
  there is no manual control (the generic list has up/down via `move_item`, the shopping list
  does not). A user wants to order the list the way they walk the store — entrance to checkout.
  *Needs a design decision:* is this (a) a **per-user aisle order** preference (reorder the
  aisle *sections*, persisted per user, independent of any one list), (b) **within-aisle item
  order** (sort each aisle by `position`, give rows up/down like the generic list), or (c)
  both? (a) is the stronger match for the stated use case ("where in the store items are
  placed") and is new schema (a per-user `AisleOrder` or a JSON preference). Write the design
  slice when picked up. Sibling of [[11.12]]/[[11.13]] in being pure UI/UX, but this one needs
  real design.

- [x] **11.25 — `<details>` menus and typeahead dropdowns do not close on outside click**
  *Found in:* task 07 dev test (finding 5b). App-wide, task 02 territory.
  *Issue:* every `<details class="nav-menu">` (nav profile/overflow menu, "Add to list ▾",
  "Add to book ▾") stays open until its own summary is clicked again, and opening a second
  leaves the first open. The custom typeahead result dropdowns (`static/js/recipe-editor.js`
  `.component-results` on the recipe ingredient / sub-recipe rows and the dish recipe row) have
  the same problem — they don't dismiss on outside click or blur.
  **Fixed in the task 07 continuation (2026-09-05):** new `static/js/menus.js`, loaded from
  `base.html`. Closes open `details.nav-menu` disclosures and empties typeahead
  `.component-results` on outside-click and Escape, and closes other open disclosures when one
  opens. `recipe-editor.js` unchanged (it already clears results on a pick). Native `<details>`
  still works with no JS. See `Plan/07-Lists-And-Shopping/tasks.md` 07.18.

- [ ] **11.26 — Lists have no share control in the UI**
  *Found in:* task 07 review (NB) + task 07 dev test (finding 9).
  *Issue:* `List` is an `OwnedModel` and the view-only sharing infrastructure (task 03) applies,
  but no share entry point was ever put on the list pages, so a list cannot be shared by
  clicking anything. Wanted (near-term, view-only): reuse task 03's `_partials/_share_modal.html`
  on the list index / detail pages, exactly as recipes/dishes/books do. Editable/collaborative
  sharing is task 13, not this. Small — just wiring an existing partial + the share view/action
  for `List`.

- [ ] **11.27 — `MENU` and `MEAL_PLAN` list kinds are behaviourally identical to `GENERIC`**
  *Found in:* task 07 dev test (finding 1).
  *Issue:* only `SHOPPING` has distinct behaviour; `MENU`, `MEAL_PLAN`, and `GENERIC` differ
  only in their label and index grouping heading. Decide: keep them as harmless labels, keep
  only `MEAL_PLAN` (task 08 may use it) and drop `MENU`, or collapse to `SHOPPING` + `GENERIC`.
  Cosmetic; resolve whenever task 08 settles whether it creates a `MEAL_PLAN`-kind list.

- [ ] **11.28 — `PlanShareView` / `PlanUnshareView` resolve the plan via `visible_to`, not `_owned_plan`**
  *Found in:* task 08 review pass 3 (NB5), 2026-09-07. `planner/views.py` (`PlanShareView.post`,
  `PlanUnshareView.post`).
  *Issue:* both do `get_object_or_404(MealPlan.objects.visible_to(request.user), pk=pk)` where
  `PlanDeleteView` / `PlanShareModalView` use the owner-only `_owned_plan(request, pk)` helper.
  **No security or behaviour gap** — a sharee's submit is still refused inside `share()` /
  `unshare()` (`_require_can_manage_sharing` raises Django `PermissionDenied` → 403, confirmed
  by `test_plan_share_is_owner_only`) — purely an inconsistency with the sibling views. Fix is
  two lines: swap the `get_object_or_404` for `_owned_plan(request, pk)` in both. Carried
  forward from the 08.17 F2 parity note.

- [ ] **11.29 — Planner manual-swap `<select>` renders two empty `<option>`s when a slot is filled**
  *Found in:* task 08 review pass 3 (NB7), 2026-09-07.
  `templates/planner/_partials/_slot_card.html` (~line 69).
  *Issue:* when the slot has a dish, the swap control renders both a "Swap / clear…"
  `<option value="">` and a "— clear this slot —" `<option value="">`. Harmless (both submit an
  empty `dish`, which clears the slot) but odd markup. Drop the duplicate or merge the labels.
  Fold into any future planner UI polish pass. Sibling of [[11.12]] / [[11.13]] / [[11.15]].
