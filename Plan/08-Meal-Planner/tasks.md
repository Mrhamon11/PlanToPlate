# 08 — Meal Planner · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **08.1 — `MealPlanProfile` model**
  All eight gears, with validators (`days` 1–7, `min_rating` 1–5, non-empty `slots`) and a
  one-default-per-user constraint.
  *Files:* `planner/models.py`

- [ ] **08.2 — `MealPlan` and `MealPlanEntry`**
  Including `seed`, `profile_snapshot`, `is_locked`, and the unique day/slot constraint.
  Wire `lists.ListItem.generated_from` to the real model.
  *Files:* `planner/models.py`, migration in `lists/`

- [ ] **08.3 — Candidate pool builder**
  `build_candidate_pool(user, profile)` applying scope, exclusions (through flattened
  ingredients), rating, favourites, time, and no-repeat.
  *Files:* `planner/services/candidates.py`
  *Done when:* every gear demonstrably narrows the pool, and exclusions catch sub-recipe
  ingredients.

- [ ] **08.4 — The generator**
  Seeded RNG, weighted selection, template handling, tag-limit budgets, bounded backtracking,
  `PlanResult` with reasons.
  *Files:* `planner/services/generate.py`
  *Done when:* the same seed produces identical output and an over-constrained request returns
  a partial plan with reasons instead of hanging.

- [ ] **08.5 — Dish composition from recipes**
  Compose a transient protein + carb + vegetable dish when no existing Dish fits.
  *Files:* `planner/services/compose.py`
  *Done when:* composed dishes are not persisted unless the plan is saved.

- [ ] **08.6 — Plan persistence**
  Save a previewed plan atomically, persisting composed dishes only on save.
  *Files:* `planner/services/persist.py`

- [ ] **08.7 — Regeneration**
  Respect `is_locked`, consume locked entries' tag budget, accept a new seed.
  *Files:* `planner/services/generate.py`

- [ ] **08.8 — Shopping list integration**
  Orchestrate task 07's `populate_shopping_list`. **No new flattening or aggregation logic
  belongs here** — if it seems necessary, it belongs in 05/06/07.
  *Files:* `planner/services/shopping.py`

- [ ] **08.9 — Serializers**
  Profile, plan, entry, `PlanResult`, and the generate-request serializer.
  *Files:* `planner/serializers.py`

- [ ] **08.10 — API viewsets**
  Profiles, plans, generate-preview, persist, regenerate, entry patch, reroll, shopping-list
  generate and preview.
  *Files:* `planner/api.py`, `planner/urls.py`

- [ ] **08.11 — Profile editor UI**
  The eight gears grouped into four sections with sensible defaults.
  *Files:* `planner/views.py`, `templates/planner/profile_form.html`

- [ ] **08.12 — Generate and plan grid UI**
  Week grid on desktop, stacked on mobile; lock, re-roll, and manual swap per slot; unfilled
  slots showing their reason inline.
  *Files:* `templates/planner/plan_detail.html`, `_partials/_slot_card.html`

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
