# 14 — Planner Dish Construction · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

> **Start only after task 08 is COMPLETE and merged.** This task rewrites parts of
> `planner/services/{generate,persist,compose,shopping}.py` and `MealPlanEntry`.

> **This is a planner task — treat it like the always-split ones.** Keep review chunks to
> ~4–6 subtasks. Suggested split: **14.1–14.5** (models + generator + persistence — the
> behaviour change), then **14.6–14.9** (materialise service + shopping + share + API), then
> **14.10–14.14** (UI + tests + living doc).

- [ ] **14.1 — Profile construction gear**
  `MealPlanProfile.allow_dish_construction` (bool, default `False`) and `construction_slots`
  (`PositiveSmallIntegerField`, default `0`, `MaxValueValidator(MAX_DAYS)`). Migration.
  `build_profile_snapshot` records both keys. Model `clean()` needs nothing new for these.
  *Files:* `planner/models.py`, `planner/services/persist.py`, migration
  *Done when:* a profile round-trips both fields; the snapshot carries them.

- [ ] **14.2 — `MealPlanEntry` composed state**
  `composed_recipe_ids` (`JSONField(default=list, blank=True)`) and `composed_name`
  (`CharField(max_length=200, blank=True)`). Migration. `MealPlanEntry.clean()` enforces the
  three-state invariant (real dish XOR composed XOR unfilled — never `dish` set *and*
  `composed_recipe_ids` non-empty). A `compose.transient_dish_from_ids(ids)` helper builds an
  unsaved `Dish` with `_composed_recipes` / `_composed_tags` / `_is_composed` from stored ids.
  *Files:* `planner/models.py`, `planner/services/compose.py`, migration
  *Done when:* saving an entry with both a dish and composed ids raises `ValidationError`.

- [ ] **14.3 — One-pot and mixed composition**
  `compose.build_one_pot_recipe_pool(user, profile)` (visible_to, excluded-tag /
  excluded-ingredient filtered, ordered by pk, built once) and
  `compose.compose_one_pot_dish(pool, rng, *, avoid_recipe_ids, forbidden_signatures,
  max_total_minutes, tag_budget)` returning an unsaved single-component `Dish` or `None` under
  the same degradation rules as `compose_balanced_dish`. Single-id `frozenset` signatures.
  *Files:* `planner/services/compose.py`
  *Done when:* `ONE_POT` construction picks only a one-pot-role recipe; `None` when none exists.

- [ ] **14.4 — Budgeted, RNG-mixed construction in the generator**
  `generate_plan(..., construction_slots: int | None = None)`. `None` derives from the
  profile; an explicit int wins and enables construction for the run even if the toggle is
  off; `0` disables. Per-slot seeded coin flip (RNG consumed **only** when budget remains) →
  construct-first or real-dish-first. `constructions_used` counter, capped at the effective
  `construction_slots`. The existing strict-`BALANCED` fallback is **unchanged** and **not**
  counted against the cap. `MIX` construction alternates via `_slot_template`. Byte-identical
  output preserved with construction off *and* on. Honest degradation for a missing role pool.
  *Files:* `planner/services/generate.py`
  *Done when:* `test_generate.py`'s determinism test passes with construction enabled, and at
  most `construction_slots` opt-in compositions appear.

- [ ] **14.5 — Persistence: store composed state, stop materialising**
  Delete `persist._materialise_composed_dish`. `save_plan` / `update_plan_in_place` /
  `reroll_entry` write `composed_recipe_ids` + `composed_name` onto `MealPlanEntry` for a
  composed `PlanResult` entry (`dish=None`), never create a `Dish`. `update_plan_in_place`
  leaves locked entries untouched; unlocked composed entries are rewritten. A re-roll from
  composed → real dish clears the composed fields. Regeneration seeds `constructions_used`
  with the locked-composed count. Manual swap to a real dish clears composed fields and
  `is_locked` (D50).
  *Files:* `planner/services/persist.py`, `planner/serializers.py` (entry `update`),
  `planner/views.py` (`PlanEntrySwapView`)
  *Done when:* saving a plan with composed slots creates **zero** `Dish` rows;
  `test_persist.py` asserts it.

- [ ] **14.6 — `save_composed_entry_as_dish` service**
  New `planner/services/materialise.py`. Owner-only; `409`/`PlannerError` if the entry already
  has a dish; refuses if any stored recipe id is no longer `visible_to(user)`. Creates
  `Dish(owner=user, visibility=PRIVATE)` + ordered `DishComponent`s (`servings=Decimal(1)`),
  attaches validated tags, points `entry.dish` at it, clears `composed_recipe_ids` /
  `composed_name`. One transaction.
  *Files:* `planner/services/materialise.py`
  *Done when:* calling it twice on the same entry raises; a non-owner is refused.

- [ ] **14.7 — Shopping-list orchestration over composed entries**
  `shopping._planned_dishes` also yields `compose.transient_dish_from_ids(entry.composed_recipe_ids)`
  for each composed entry. **No flatten / aggregate / scale logic added** — the transient
  dish goes straight into task 07's `populate_shopping_list` / `preview_shopping_list`.
  *Files:* `planner/services/shopping.py`
  *Done when:* a plan of only composed entries produces a correct shopping list; composed-meal
  lines carry no `ListItem.dish` (provenance via `generated_from` only — accepted, D43 amend).

- [ ] **14.8 — Share cascade over composed recipes**
  `MealPlan.share_dependencies()` returns scheduled dishes **plus** the distinct `Recipe`s
  referenced by composed entries. `_validate_cascade` refuses the share — naming the recipe —
  if a composed recipe the plan owner does not own is not already visible to the recipient.
  *Files:* `planner/models.py`
  *Done when:* sharing a plan whose composed slot uses a recipe the recipient cannot see is
  refused; sharing otherwise grants read on the composed recipes' graphs.

- [ ] **14.9 — API surface**
  `MealPlanProfileSerializer`: the two new gears (validate `construction_slots` 0..7).
  `generate` / `regenerate` actions + `GeneratePreviewSerializer`: optional `construction_slots`
  override. New `POST /api/planner/plans/<id>/entries/<entry_id>/save-as-dish/` action
  (`IsOwner`; `201` / `409` / `403`). `MealPlanEntrySerializer`: `composed_recipe_ids`
  (read-only), `composed_name`, corrected `is_composed`, `component_recipes` (`[{id, name}]`
  with `name` nulled for an invisible recipe — D48 parity). `PATCH` of `dish` clears composed
  fields.
  *Files:* `planner/api.py`, `planner/serializers.py`, `planner/api_urls.py`

- [ ] **14.10 — Profile editor UI**
  Checkbox + "up to __ nights" number under `dish_template` in the *What* group, with the
  one-line explainer from `design.md`.
  *Files:* `templates/planner/profile_form.html` (or the profile form partial), `planner/forms.py` if one exists

- [ ] **14.11 — Generate-screen override**
  "New dishes this week" number field next to the days override. Empty = profile; `0` = none;
  `N` = up to N (enables construction for the run). Hand-rolled to match the days field.
  *Files:* `templates/planner/plan_generate.html`, `planner/views.py` (`PlanGenerateView`)

- [ ] **14.12 — Composed-slot card + "Save as dish" flow**
  Slot card renders `composed_name`, linked component recipes (re-filtered `visible_to`), a
  "composed" badge, and a "Save as dish" control. HTMX: `hx-get` a form into `#modal` (D39 —
  no `hx-confirm`), `POST` with an explicit `hx-target` on the slot card, response swaps the
  card + clears `#modal` OOB. No-JS: the control is a real link to a standalone
  `/planner/plans/<id>/entries/<entry_id>/save-as-dish/` page. Remove the old
  `notes == "Auto-composed…"` label logic.
  *Files:* `templates/planner/_partials/_slot_card.html`, a new
  `_save_composed_form.html`, `planner/views.py`, `planner/urls.py`, `static/css/*`

- [ ] **14.13 — Tests + manual verification**
  Every row in `test-plan.md`. Flip the existing auto-materialise assertions in
  `test_persist.py`. Run the four manual checks and report them.
  *Files:* `planner/tests/*`

- [ ] **14.14 — Living document**
  Task 14 → AWAITING APPROVAL in `MILESTONES.md` with a 2–3 line row and its place in the
  dependency order (after 08; not on the critical chain to 09/10). `ARCHITECTURE.md`: record
  the **10th gear** (cap raised 9 → 10, with rationale); amend **D49** (no auto-materialise —
  composed dinners are temp `MealPlanEntry.composed_recipe_ids`), **D50** (construction
  budget / override / RNG-mix / locked-slot budget / swap clears composed), **D43** (a
  planner-composed meal's list lines carry no `ListItem.dish`), **D47** (`share_dependencies`
  includes composed recipes), **D48** (`component_recipes` name-tombstoning). Retire the
  `is_auto_composed`-by-`notes`-string BACKLOG item.
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`, `Plan/BACKLOG.md`
