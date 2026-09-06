# 08 — Meal Planner · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **08.1 — `MealPlanProfile` model**
  All eight gears, with validators (`days` 1–7, `min_rating` 1–5, non-empty `slots`) and a
  one-default-per-user constraint.
  *Files:* `planner/models.py`

- [x] **08.2 — `MealPlan` and `MealPlanEntry`**
  Including `seed`, `profile_snapshot`, `is_locked`, and the unique day/slot constraint.
  Wire `lists.ListItem.generated_from` to the real model.
  *Files:* `planner/models.py`, migration in `lists/`

- [x] **08.3 — Candidate pool builder**
  `build_candidate_pool(user, profile)` applying scope, exclusions (through flattened
  ingredients), rating, favourites, time, and no-repeat.
  *Files:* `planner/services/candidates.py`
  *Done when:* every gear demonstrably narrows the pool, and exclusions catch sub-recipe
  ingredients.

- [x] **08.4 — The generator**
  Seeded RNG, weighted selection, template handling, tag-limit budgets, bounded backtracking,
  `PlanResult` with reasons.
  *Files:* `planner/services/generate.py`
  *Done when:* the same seed produces identical output and an over-constrained request returns
  a partial plan with reasons instead of hanging.

- [ ] **08.5 — Dish composition from recipes**
  Compose a transient protein + carb + vegetable dish when no existing Dish fits.
  *Files:* `planner/services/compose.py`
  *Done when:* composed dishes are not persisted unless the plan is saved.
  *Carried-forward note (08.4 rework):* the strict-BALANCED path now has **no dish-level
  fallback** — a BALANCED profile whose library holds no role-complete dish produces an
  all-unfilled plan (correctly explained) until this composition seam lands. Do not defer
  08.5 past the next run; it is the only thing standing between a BALANCED-default profile
  and a first-run empty grid.

- [ ] **08.6 — Plan persistence**
  Save a previewed plan atomically, persisting composed dishes only on save.
  *Files:* `planner/services/persist.py`
  *Carried-forward review finding (08.1–08.4 review):* `MealPlan.profile_snapshot` ships as
  `JSONField(default=dict)`, so a plan can persist with an empty snapshot even though the
  design treats it as server-generated and required. The persist service **must** always
  populate `profile_snapshot` from the live profile before saving.

- [ ] **08.7 — Regeneration**
  Respect `is_locked`, consume locked entries' tag budget, accept a new seed.
  *Files:* `planner/services/generate.py`
  *Carried-forward review findings:*
  - (08.1–08.4 review) the generator loads `entry.dish.tags.all()` per locked entry that is
    not already in the candidate pool, one query each (bounded by `days`, ~7). While
    reworking this path, prefetch those tags.
  - (08.1–08.4 review) `generate.py:97` does `bias = float(profile.favorites_bias)`,
    converting a `Decimal` to `float`. It is an `rng.choices` weight (not a measurement) and
    the comment says so, but `random.choices` accepts `Decimal` weights directly — drop the
    `float()` call while in this file.
  - (08.1–08.4 review) determinism is only tested on a pure greedy fill
    (`test_same_seed_produces_identical_plan`, 12 dishes / 7 days, no backtracking). The RNG
    stream advances during backtracking, so a regression there is uncaught. Extend a
    backtracking scenario (e.g. `test_backtracking_bounded`) to also assert two runs at the
    same seed produce identical entries.
  - (08.1–08.4 review) `test_no_duplicate_dishes_within_plan` does not exercise the
    test-plan's "unless the pool is too small" clause — the generator never emits a
    duplicate, it leaves the slot unfilled (see `test_partial_plan_when_pool_too_small`).
    Reword the `test-plan.md` row to match the implemented (better) behaviour: no duplicates
    ever; too-small pool yields unfilled slots.
  - (08.1–08.4 review) `test_pool_query_count`'s absolute upper bound (`< 30`) is loose; the
    equality assertion is the real N+1 guard. Tighten the cap to the observed count + small
    headroom when convenient.

- [ ] **08.8 — Shopping list integration**
  Orchestrate task 07's `populate_shopping_list`. **No new flattening or aggregation logic
  belongs here** — if it seems necessary, it belongs in 05/06/07.
  *Files:* `planner/services/shopping.py`

- [ ] **08.9 — Serializers**
  Profile, plan, entry, `PlanResult`, and the generate-request serializer.
  *Files:* `planner/serializers.py`
  *Carried-forward review findings (08.1–08.4 review):*
  - `MealPlanProfile.slots` non-empty is enforced only by the model `clean()` validator —
    there is no DB `CheckConstraint` like `days` / `min_rating` have, so
    `MealPlanProfile.objects.create(slots=[])` bypasses it. The profile serializer must
    validate `slots` is non-empty.
  - `MealPlan` is `contains_owned_children = False` (D44). The `MealPlanEntry` serializer
    **must** filter each entry's `dish` through `Dish.objects.visible_to(request.user)` (or
    equivalent) — otherwise a shared plan leaks the names of dishes the recipient cannot
    see. This is currently enforced nowhere; the docstring's claim that "a recipient sees
    only entries whose dish is already visible" is aspirational until this serializer lands.

- [ ] **08.10 — API viewsets**
  Profiles, plans, generate-preview, persist, regenerate, entry patch, reroll, shopping-list
  generate and preview.
  *Files:* `planner/api.py`, `planner/urls.py`
  *Carried-forward review finding (08.1–08.4 review):* `build_candidate_pool(user, profile)`
  and the generator trust that `profile` belongs to `user` — the visibility keystone still
  holds (scope + stats gates use the passed `user`, not `profile.owner`) so nothing leaks,
  but a mismatched profile would apply someone else's knobs. This viewset **must** enforce
  `profile.owner == request.user` on generate/preview/persist/regenerate (test-plan already
  has `test_cannot_generate_from_others_profile`).

- [ ] **08.11 — Profile editor UI**
  The eight gears grouped into four sections with sensible defaults.
  *Files:* `planner/views.py`, `templates/planner/profile_form.html`

- [ ] **08.12 — Generate and plan grid UI**
  Week grid on desktop, stacked on mobile; lock, re-roll, and manual swap per slot; unfilled
  slots showing their reason inline.
  *Files:* `templates/planner/plan_detail.html`, `_partials/_slot_card.html`
  *Carried-forward review finding (08.1–08.4 review):* `MealPlanEntry.Meta.ordering` is
  `["day_index", "slot"]`, which sorts slots alphabetically (BREAKFAST, DINNER, LUNCH), not
  chronologically. The grid needs to impose an explicit meal-order (breakfast → lunch →
  dinner → …) rather than relying on the model default.

- [ ] **08.13 — Shopping list preview and generation UI**
  Preview with a staples toggle, plus the task 07 warning when checked items would be replaced.
  *Files:* `templates/planner/_partials/_shopping_preview.html`

- [ ] **08.14 — Empty-state handling**
  A user with no dishes gets a clear explanation and a route forward, not a blank grid.
  *Files:* `templates/planner/_partials/_empty_pool.html`

- [ ] **08.14a — Light up the "Planner" home card**
  `templates/core/_partials/_home_content.html` still renders Planner as a non-interactive
  "Coming soon." card (a task-02 placeholder; 04-07 wired up their own on the way through, 07
  via 07.13a). Turn it into an `<a class="card card-link" href="/planner/">` with a one-line
  description, matching the other cards. Update `core/tests/test_templates.py`
  `test_home_dashboard_cards` (no "Coming soon." cards should remain). The richer dashboard —
  this week's plan surfaced on the home page, active shopping list, recently viewed — is
  task 12, which is best done right after this task lands.
  *Files:* `templates/core/_partials/_home_content.html`, `core/tests/test_templates.py`

- [ ] **08.15 — Update the living document**
  Task 08 → AWAITING APPROVAL. Resolve the `MealPlan`-vs-`List` open question recorded in
  `MILESTONES.md` §8.
  *Files:* `Plan/MILESTONES.md`
  *Carried-forward review findings (08.1–08.4 review) — fold into the `ARCHITECTURE.md`
  decision-log update at task completion:*
  - `design.md` was edited on this branch: `source_scope` default `MINE_AND_SHARED` → `SHARED`
    (cosmetic enum rename, semantics match ARCHITECTURE §5 gear 3) and the `MIX` template was
    expanded to describe per-slot BALANCED/ONE_POT alternation (a genuine refinement). The
    `MIX` semantics **and** the strict-BALANCED "no dish-level fallback" behaviour should land
    in the decision log, not only in `design.md` + code comments.
  - The D44 re-decision (`MealPlan.contains_owned_children = False`; sharing does not cascade;
    plan copy out of scope) currently lives only in the model docstring — ARCHITECTURE.md D44
    says task 08 "must re-decide" this, so record the outcome in the decision log.
  - `MealPlanProfile.exclude_staples` is a de-facto 9th knob (a shopping-list rendering
    option, not one of "the eight gears"). Acknowledge it against the "eight gears, capped"
    invariant in ARCHITECTURE §5 so it is not later read as a violation.

  > **Then tell the owner, explicitly, that [task 12 — Home Dashboard](../12-Home-Dashboard/design.md)
  > is the next task to run.** It is the only task gated on 08 finishing rather than on the
  > numbered chain: its two headline panels (this week's plan, the active shopping list) need
  > tasks 07 and 08 to exist, and it replaces the placeholder card grid 08.14a just finished
  > patching. Do not let it drift to the end of the project — say it out loud at handoff.
