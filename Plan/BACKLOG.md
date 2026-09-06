# Backlog — findings with no owning task

Items raised by a pipeline stage that are real but not blocking and not owned by any
planned task. Each line: what, where it came from, why it is not urgent.

## UI polish

- **`tag_limits` per-tag widget on the profile form.** (Task 08.12, 2026-09-06.)
  `MealPlanProfileForm.tag_limits` is still a raw JSON textarea. A per-row widget (tag
  dropdown + number input) would be friendlier. Not urgent — the JSON field validates and
  the help text carries an example.

## Meal planner — follow-ups

- **A saved plan cannot show *why* a slot is unfilled.** (Task 08.12 dev run, 2026-09-06.)
  `MealPlanEntry` has no field to persist the generator's per-slot reason string, so a
  saved plan's empty slot shows a generic "re-roll or pick a dish" line — only the live
  *preview* grid shows the full reason inline. Closing this needs a `reason`/`unfilled_reason`
  CharField on `MealPlanEntry` (+ migration) and the persist path to carry it through. Not
  urgent: the preview is where a user decides, and a saved empty slot is still re-rollable.

- **`_shopping_preview.html` has no non-JS path.** (Task 08.13 dev run, 2026-09-06.)
  The shopping-list preview on the plan detail page is `hx-get` only — there is no plain
  link/GET route that renders it standalone. The POST "generate shopping list" path *does*
  work without JS. Minor tension with the "works without JS" rule; worth a standalone view
  if it matters.

- **The generate screen's day/profile picker is hand-rolled HTML, not a Django `Form`.**
  (Task 08.12 dev run, 2026-09-06.) Validation is lenient (clamps out-of-range values
  rather than erroring). A `Form` would be tidier and give real field errors if the screen
  grows more knobs.

- **`update_plan_in_place` never deletes stale entry rows.** (Task 08 review, 2026-09-06.)
  `planner/services/persist.py:137-182` writes/updates entries for the `(day_index, slot)`
  pairs in `result.entries` but never deletes rows for pairs absent from it. No current path
  makes a plan's stored entries diverge from its snapshot slots, so this is unreachable
  today — but a future "edit plan slots" feature would want a defensive
  `plan.entries.exclude(...).delete()` or an assertion here.

- **`_grid_rows` calls `MealSlot(slot)` on a raw snapshot slot string.** (Task 08 review,
  2026-09-06.) `planner/views.py:285`. A `profile_snapshot` carrying a slot value not in the
  `MealSlot` enum (only reachable if the enum is ever narrowed after plans exist) raises
  `ValueError` → 500. Very low risk today. If `MealSlot` is ever touched, guard this with a
  `.get`-style fallback that skips or labels the unknown slot.

- **`generate` API action ignores `start_date` and cannot take `days`.** (Task 08 review,
  2026-09-06.) `planner/api.py:119-130` / `planner/serializers.py:335-345`.
  `GeneratePreviewSerializer` *requires* `start_date` but the action never passes it to
  `generate_plan`, and unlike the HTML `PlanGenerateView` there is no `days` parameter, so an
  API preview is always `profile.days` long. Matches the design's API table literally but the
  required-yet-unused field is a wart and the HTML/API capability mismatch is surprising.
  Either drop `start_date` from the generate serializer or accept `days` there for parity;
  note the resolution in `design.md`'s API section.

- **N+1 on the plan *list* API endpoint.** (Task 08 review, 2026-09-06.)
  `planner/serializers.py:272-288` — `MealPlanSerializer.get_entries` → `_entry_context` runs
  one `visible_to` dish-id query per plan in the list. Fine at this project's scale (10-20
  users, few plans) but it will drift. Resolve visible-dish-ids once across the whole page
  like `lists.serializers.visible_item_target_caches` does.

- **`is_auto_composed` on a saved plan is detected by `notes` string equality.** (Task 08
  review, 2026-09-06.) `planner/views.py:456-458` and
  `templates/planner/_partials/_slot_card.html` compare
  `entry.dish.notes == "Auto-composed by the meal planner."`. A user dish that happens to
  carry that exact note is mislabeled; editing a materialised composed dish's notes drops the
  marker. Cosmetic only. A `copied_from`-style marker or a dedicated flag on `Dish` /
  `MealPlanEntry` would be sturdier.
  *(08 review pass 2, 2026-09-06.)* Same root cause surfaces in the API:
  `MealPlanEntrySerializer.get_is_auto_composed` (`planner/serializers.py:179-187`) relies on
  `is_composed(dish)`, which requires `dish.pk is None` — true only for a transient preview
  dish — so a **saved** plan's composed slots serialize as `is_auto_composed: false` while the
  HTML grid still marks them via the `notes` check. A durable composed-dish marker fixes both.

- **Backtracking can over-release `composed_recipe_ids`.** (Task 08 review, 2026-09-06.)
  `planner/services/generate.py:226-233` — when a backtrack sweep clears a range containing a
  composed slot, `composed_recipe_ids.difference_update(recipe_ids)` can remove ids still
  used by a *standing* composed dish, weakening the `avoid_recipe_ids` variety preference for
  later compositions in the same pass. `avoid` is a preference not a constraint,
  `forbidden_signatures` still prevents identical trios, and output stays deterministic — so
  this is a minor quality nick in a rare path. Track released ids per-slot and only drop
  those not referenced by another surviving `composed_at` entry.

- **`test_generation_time_bounded` is weaker than it reads.** (Task 08 review, 2026-09-06.)
  `planner/tests/test_security.py:253-272` — the "hostile" profile sets 30 zero tag-limits,
  but the `pool` fixture's dishes carry no tags, so the limits never bite and no real
  backtracking pressure is created. `test_never_hangs_on_impossible_constraints` and
  `test_backtracking_bounded` in `test_generate.py` are the real guards. Give the hostile
  profile's dishes tags that collide with its limits so the CPU-DoS guard actually exercises
  the backtrack cap.

- **`PlanShoppingPreviewView` staples-checkbox pre-checked state ignores the snapshot
  fallback.** (Task 08 review pass 2, 2026-09-06.) `planner/views.py:623-624` — when
  `plan.profile` is deleted, `effective` for the staples checkbox defaults to `True`, but the
  service (`shopping._staples_default`) reads `profile_snapshot["exclude_staples"]`. The
  generated list is still correct; only the pre-checked state of the toggle can disagree with
  what regeneration would do. Fix: reuse `shopping._staples_default(plan)` for the display
  value.

- **`test_plan_idor_matrix` accepts `(403, 400)` for a sharee's regenerate / reroll.**
  (Task 08 review pass 2, 2026-09-06.) `planner/tests/test_security.py:93-114`. The
  permission layer should reject with 403 *before* the view body runs; accepting 400 would
  let a regression that reordered the checks pass silently. The test still asserts the
  security property (`shared_entry.is_locked is False` afterwards) — this is a strictness
  nit. Tighten the assertion to `== 403`.

## Robustness

- **`explain_empty_pool` shallow-copies the profile model instance.**
  (Task 08 subtask 08.5–08.8 review, 2026-09-06.) `planner/services/candidates.py:108`
  does `copy.copy(profile)` to build a "relaxed" pool, then reads the copy's M2M managers.
  It works because the copy keeps the same pk, but it is fragile — a future field cached on
  `_state` or a prefetch cache could make the relaxed pool disagree with a real one. Cleaner
  to pass an explicit override kwarg (e.g. `no_repeat_days_override`) into
  `build_candidate_pool` instead of copying the instance. No planned task owns this.
