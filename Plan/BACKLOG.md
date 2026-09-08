# Backlog — findings with no owning task

Items raised by a pipeline stage that are real but not blocking and not owned by any
planned task. Each line: what, where it came from, why it is not urgent.

## Meal planner — follow-ups

- **A saved plan cannot show *why* a slot is unfilled.** (Task 08.12 dev run, 2026-09-06.)
  `MealPlanEntry` has no field to persist the generator's per-slot reason string, so a
  saved plan's empty slot shows a generic "re-roll or pick a dish" line — only the live
  *preview* grid shows the full reason inline. Closing this needs a `reason`/`unfilled_reason`
  CharField on `MealPlanEntry` (+ migration) and the persist path to carry it through. Not
  urgent: the preview is where a user decides, and a saved empty slot is still re-rollable.

- **The unfilled-slot reason banner is recomputed from the *live* profile, not the
  snapshot.** (Task 08 review pass 3, 2026-09-07.) `planner/views.py`
  `PlanDetailView._add_unfilled_explanation` re-runs `regenerate_plan` against the plan's
  current `MealPlanProfile`, so if the profile's knobs were edited after the plan was saved
  the banner explains the empty slots using today's settings, not the ones in force at
  generation time — the `profile_snapshot` exists precisely to keep a saved plan explicable
  after its profile changes. Closing this means teaching `generate_plan` / `regenerate_plan`
  to run from a snapshot dict rather than a live model instance. Pairs with the persisted-
  `reason` item above; a persisted per-slot reason retires both. Not urgent — at this scale
  profiles rarely change under a saved plan.

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
  *(Task 12 review, 2026-09-07.)* Task 12's `design.md` carried this as a "Carried-in finding"
  expecting the dashboard to add a panel listing a user's plans and thereby expose the N+1.
  That panel was not built — "This week" handles a single plan and the dashboard API uses its
  own `ThisWeekPanelSerializer`, not `MealPlanSerializer` — so the N+1 is neither fixed nor
  newly exposed. It lives here now; task 12's `design.md` will stop being read once the task
  closes.

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
  *(08 review pass, post-08.18, 2026-09-07.)* Still open. The marker string
  `"Auto-composed by the meal planner."` is now duplicated across three call sites
  (`persist._materialise_composed_dish` and two view sites); the durable-marker fix should
  also extract a `COMPOSED_DISH_NOTES` constant and a single `is_auto_composed(dish)` helper.
  *(Now owned by task 14 — `Plan/14-Planner-Dish-Construction/`.)* Task 14 replaces
  auto-materialisation entirely: composed dinners become temp `MealPlanEntry.composed_recipe_ids`
  and the marker string / `notes`-equality check go away. Strike this item when 14 lands.

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

- **`test_plan_idor_matrix` accepts `(403, 400)` for a sharee's regenerate / reroll.**
  (Task 08 review pass 2, 2026-09-06.) `planner/tests/test_security.py:93-114`. The
  permission layer should reject with 403 *before* the view body runs; accepting 400 would
  let a regression that reordered the checks pass silently. The test still asserts the
  security property (`shared_entry.is_locked is False` afterwards) — this is a strictness
  nit. Tighten the assertion to `== 403`.

- **`compose_balanced_dish` is single-shot against `forbidden_signatures`.** (Task 08 final
  review, 2026-09-07.) `planner/services/compose.py` (~lines 120–147) makes one `rng.choice`
  per role, builds the protein+carb+vegetable trio, and returns `None` if that trio's
  signature is already placed in the plan — without trying another combination even when the
  role pools hold other distinct valid trios. On a library with several role-tagged recipes a
  BALANCED slot can go unfilled on an unlucky draw while a valid distinct composition still
  exists. Honest degradation (deterministic, never a duplicate, carries a reason) — not a
  correctness bug, just suboptimal result quality on a larger library. Fix: bounded retry, or
  filter forbidden combos out of the per-role candidate lists before `rng.choice`.

- **`collect_recipe_ingredient_ids` silently truncates at `depth > MAX_DEPTH`.** (Task 08
  review pass, post-08.18, 2026-09-07.) `planner/services/candidates.py` (~line 188) stops
  the allergy-exclusion recipe walk when `depth > MAX_DEPTH`, whereas
  `recipes.services.flatten` *raises* `DepthExceededError` at the same cap. A graph deeper
  than `MAX_DEPTH` would stop checking ingredients past depth 5, so an excluded allergen
  nested deeper than 5 levels would not remove the dish from the candidate pool. Only
  reachable if such a graph exists at all, which the write-path cycle/depth guard is supposed
  to prevent — hence non-blocking. Fix: either match `flatten`'s raise, or add a comment
  stating the truncation is intentional and safe because the write path is guarded.

## Home dashboard — follow-ups

- **`_suggestion` uses `Dish.objects.order_by("?")`.** (Task 12.10 dev run, 2026-09-07.)
  `core/services/dashboard.py::_suggestion` does a full-table random sort to pick "what should
  I make?". Fine at this project's scale (a household's dish library is small); if a library
  ever grows large this is the line to revisit — swap for `random` over a cheap id list, or a
  count + offset. Not urgent.

- **Pre-existing `ruff format` drift on `master`.** (Noticed during task 12, 2026-09-07.)
  `planner/serializers.py` and `planner/tests/test_views.py` report formatting drift from the
  committed task-08 merge (`ff4510b`) — not task 12's code. `uv run ruff format` on just those
  two files, as a standalone commit on `master`, clears it. Flagged not fixed here to keep the
  task-12 diff clean.

- **`_this_week` can hide a still-active plan when a more-recently-*started* plan has ended.**
  (Task 12 review, 2026-09-07.) `core/services/dashboard.py::_this_week` takes the single
  most-recently-started owned plan with `start_date <= today`; if that one has already ended it
  returns the empty state without considering an older, longer plan that still covers today.
  Needs two overlapping owned plans (a short plan layered over a week) — uncommon but possible.
  Fix: annotate a computed end date (`start_date + days - 1`) and filter to plans whose end is
  `>= today` before `order_by("-start_date").first()`.

- **Shopping panel renders for an empty / fully-checked default list** instead of the design's
  "Nothing on the list" empty state. (Task 12 review, 2026-09-07.)
  `core/services/dashboard.py::_shopping` returns a `ShoppingPanel` whenever a default list
  exists, regardless of item count; the template then shows "0 of 0 items checked". Cosmetic —
  arguably consistent with the design's stated empty state. Tighten only if the empty panel
  looks wrong in the fedora-headless walkthrough.

- **Test gaps in the dashboard panels.** (Task 12 review, 2026-09-07.)
  (a) Shopping panel: no direct test of `SHOPPING_PREVIEW_LIMIT` truncation, `group_by_aisle`
  output, checked-items-excluded, or the `hidden_unchecked` "+ N more" count — exercised only
  indirectly through `test_dashboard_query_count`. Add
  `test_shopping_panel_preview_is_capped_and_grouped`.
  (b) `_this_week`: `_SLOT_ORDER` slot ordering (breakfast/lunch/dinner within a day) and the
  overlapping-plan case above are untested.

- **`test_viewing_twice_updates_not_appends` asserts `viewed_at >= first`, not `>`.**
  (Task 12 review, 2026-09-07; already noted in `Plan/12-Home-Dashboard/tasks.md` 12.7.)
  A "timestamp stops bumping" regression slips through if both writes land in one clock tick.
  Needs `freezegun` / `time-machine` (a new test-only dependency — owner sign-off) to pin the
  clock and assert a strict bump. Fold into the N4 polish pass.

- **`EmptyPanel` vs real-panel discrimination is by attribute presence.** (Task 12 re-review,
  2026-09-07.) `_panel_this_week.html` / `_panel_shopping.html` branch on
  `{% if dashboard.this_week.forward_url %}`; `core/serializers.py` branches on
  `isinstance(..., EmptyPanel)`. The template side relies on a missing attribute resolving to
  an empty string via `string_if_invalid`. Works today; a `string_if_invalid` change or a
  stray `forward_url` attribute would flip the branch silently. Fix: add an explicit
  `is_empty` flag to the panel dataclasses, or hand the template distinct context keys.

- **`_shared_with_you` does not `.exclude(is_system=True)`** whereas `_public_from_others`
  does. (Task 12 re-review, 2026-09-07.) `core/services/dashboard.py` — a system object with
  the requester in its `shared_with` would surface in "Shared with you". Practically
  unreachable today (system objects are seeded, never shared through the API); the asymmetry
  is a latent trap if sharing of system objects is ever added. One `.exclude` call; add a
  test alongside. Fold into the N4 polish pass.

- **`test_home_dashboard_cards` does not assert the per-section counts.**
  (Task 12 re-review, 2026-09-07.) `core/tests/test_templates.py` — `test-plan.md` 12.11 says
  this test was "updated … now with counts", but it still only asserts the five links resolve
  and no "Coming soon." remains. Service-layer coverage exists
  (`test_dashboard.py::test_section_counts_are_visibility_scoped`), so a dropped
  `SectionCount.count` in the markup is still caught there — only the template assertion is
  missing. Either add one count assertion or correct the test-plan wording.

- **`test_dashboard_query_count` uses a ceiling (`django_assert_max_num_queries(26)`), not an
  exact count.** (Task 12 re-review, 2026-09-07.) `core/tests/test_dashboard.py`. A regression
  that adds queries while staying ≤ 26 slips through. `tasks.md` 12.15 calls 26 the measured
  floor — if so, `django_assert_num_queries(26)` is the stronger assertion. Tighten when the
  number is next re-measured.

- **`DashboardPanelView` rebuilds the whole dashboard to render one fragment.**
  (Task 12 re-review, 2026-09-07.) `core/views.py` — `build_dashboard()` runs every panel
  (~26 queries) to return a single panel's HTML. Only the "suggestion" re-roll uses it today,
  so the cost is one wasteful request per re-roll. Related to `tasks.md` 12.13 (N5, unlinked
  panel names). When more panels get in-place refresh, build only the requested panel.

## New features — need their own task folder

- **Pantry / on-hand list type.** (Task 08 manual dev-test, 2026-09-07 — owner request.)
  A list type parallel to the shopping list for food the user already has, with
  user-customisable storage locations (pantry / fridge / freezer / …) as an editable
  category. Shopping-list generation gains an optional `pantry` parameter: items already on
  hand are not added, and an item held in insufficient quantity contributes only the
  shortfall. Reuses task 05–07's flatten / aggregate / scale machinery — the new logic is the
  set-difference against pantry quantities, which belongs in `lists/services.py`, plus the
  pantry model and its UI. Sized as its own task, not a planner sub-task.

## Code hygiene

- **`ruff format` drift on two `planner/` files from the task 08 merge.** (Task 12.1–12.4
  dev run, 2026-09-07.) `planner/serializers.py` and `planner/tests/test_views.py` are
  committed in a state `ruff format .` wants to reformat — they landed unformatted through
  the task 08 merge (#11), missed because the pipeline runs `ruff format` only over files a
  task touched. Fix is one commit: `uv run ruff format planner/serializers.py
  planner/tests/test_views.py`. Harmless, but it makes every future planner task's format
  step noisy — whoever picks up task 14 (planner) can fold it in.

## Operations / dev workflow

- **Nightly prod → dev-box data refresh.** (Owner request, 2026-09-06.) Once the app is
  deployed, a scheduled job should copy the production database (and later `MEDIA_ROOT`) to
  the dev box each night, so a bug reported against prod can be reproduced and debugged
  against the same data. Should reuse task 10's backup machinery — `sqlite3 .backup` (never
  `cp` on a WAL file), off-box transfer (the dev box is on the same Tailnet; `tailscale file
  cp` or `rsync` over Tailscale SSH), then on the dev box: drop the file in place, run
  `migrate` in case the dev branch is ahead, and (optionally) scrub or keep real user data
  per the owner's call. **Best owned by task 10** (it already builds `.backup` + off-box copy
  + a restore drill; this is the same pipeline pointed at a second destination). Not urgent —
  there is no prod yet. See `Plan/10-Security-And-Deployment/design.md` → Backups.

## Robustness

- **Per-slot HTMX views have no shared message channel.** (Task 08.16 dev-test rework,
  2026-09-07.) `planner/views.py::_PlanEntryWriteMixin` subclasses are plain `View`s; to make
  the B3 "nothing changed" message reach the user, the dev appends the OOB `_messages.html`
  fragment directly in `render_card` (mirroring `core.mixins.MessageMixin`). Fine as-is, but
  if more per-slot HTMX messaging appears, fold this into a shared mixin rather than repeating
  the OOB append. No planned task owns this.

- **`_add_unfilled_explanation` recomputes the whole plan on a read path.**
  (Task 08.16 dev-test rework, 2026-09-07.) `planner/views.py` — every owner GET of a saved
  plan-detail page that has an unfilled slot runs a full `regenerate_plan()` (and sometimes a
  second `build_candidate_pool()`) to reconstruct the per-slot reasons deterministically from
  the plan's seed, because the persisted schema has no per-slot `reason` field (that field is
  its own BACKLOG item). Correct and fine for 10–20 users; revisit only if the plan-detail
  page shows up slow. Persisting the reason retires this.

- **Deleting a meal plan orphans its `source=GENERATED` shopping-list items.**
  (Task 08.16 dev-test rework, 2026-09-07.) `MealPlan.delete()` cascades its entries but the
  linked shopping `List` is a separately-owned object and survives (D44); its
  `source=GENERATED` `ListItem`s stay with `generated_from` nulled (`SET_NULL`). Arguably
  desirable — you still need the groceries — but nothing prunes generated items whose
  originating plan is gone. Decide whether `lists.services` should offer that path.

- **`explain_empty_pool` shallow-copies the profile model instance.**
  (Task 08 subtask 08.5–08.8 review, 2026-09-06.) `planner/services/candidates.py:108`
  does `copy.copy(profile)` to build a "relaxed" pool, then reads the copy's M2M managers.
  It works because the copy keeps the same pk, but it is fragile — a future field cached on
  `_state` or a prefetch cache could make the relaxed pool disagree with a real one. Cleaner
  to pass an explicit override kwarg (e.g. `no_repeat_days_override`) into
  `build_candidate_pool` instead of copying the instance. No planned task owns this.

- **`MealPlanSerializer.get_entries` is N+1 across plans.** (Task 08 review 2026-09-06;
  moved here by the task 12 reviewer, 2026-09-07.) `planner/serializers.py` builds
  `_entry_context` per plan, running one `Dish.objects.visible_to(user)` query per plan row.
  Originally parked in `Plan/12-Home-Dashboard/design.md` on the assumption task 12 would add
  a "list of plans" panel to expose it — it did not, so the finding needs a home that outlives
  task 12. Harmless at 10–20 users; fix by resolving visible dishes once page-wide and
  threading the cache through the serializer context. Best folded into any future
  planner-serializer rework.
