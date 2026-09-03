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

- [ ] **11.11 — Revoking a share / making a recipe private does not cascade to sub-recipes**
  *Found in:* task 05 dev test, `core/services/sharing.py` (`unshare`, and the visibility-down
  path in `share`).
  *Issue:* granting access cascades down the sub-recipe DAG (sharing or publishing a
  super-recipe pulls in its sub-recipes); **revoking does not**. Unshare a super-recipe and its
  sub-recipes stay shared; set a public super-recipe back to private and its sub-recipes stay
  public. Blind reverse-cascade is wrong — a sub-recipe may still back *another* recipe that is
  legitimately shared/public — so this needs a small UI (an "also revoke access to these
  sub-recipes: ☐ ☐" list, defaulting to the ones not reachable from any other still-shared
  root) plus the service work to apply the user's selection. Task 03 territory; write the
  design slice when picked up.

- [ ] **11.12 — Recipe list filter panel is too cluttered; collapse it behind a disclosure**
  *Found in:* task 05 dev test, `templates/recipes/recipe_list.html`.
  *Issue:* the whole filter form (search + role + time + rating + favourites + tag chips) is
  always expanded above the results. Wanted: show only the search box with a "▸" that expands
  the rest (Alpine is already loaded; a `<details>`/`<summary>` also works). The **Clear
  filters** link (added in 05.15) stays always-visible. Keep the no-JS path working — the
  fields must still be reachable with the disclosure closed by default only when JS is on.

- [ ] **11.13 — Ingredient / sub-recipe typeahead has no keyboard navigation**
  *Found in:* task 05 dev test, `static/js/recipe-editor.js` + `_component_row.html`.
  *Issue:* the custom typeahead dropdown can't be driven with the arrow keys / Enter the way a
  native `<select>` can — a mouse is required to pick a result. Add ArrowUp/ArrowDown to move a
  highlight through `.component-results`, Enter to choose, Escape to dismiss, with
  `aria-activedescendant` wiring for screen readers.
