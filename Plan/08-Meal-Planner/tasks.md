# 08 — Meal Planner · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **08.1 — `MealPlanProfile` model**
  All eight gears, with validators (`days` 1–7, `min_rating` 1–5, non-empty `slots`) and a
  one-default-per-user constraint.
  *Files:* `planner/models.py`

- [x] **08.2 — `MealPlan` and `MealPlanEntry`**
  Including `seed`, `profile_snapshot`, `is_locked`, and the unique day/slot constraint.
  Wire `lists.ListItem.generated_from` to the real model.
  *Files:* `planner/models.py`. (No `lists/` migration was needed — `ListItem.generated_from`
  already targeted `planner.MealPlan` in `lists/0001`; `makemigrations --check` is clean.)

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

- [x] **08.5 — Dish composition from recipes**
  Compose a transient protein + carb + vegetable dish when no existing Dish fits.
  *Files:* `planner/services/compose.py`
  *Done when:* composed dishes are not persisted unless the plan is saved.
  *Landed:* `compose.py` builds three `visible_to` recipe role pools (minus excluded
  tags / ingredients, the latter checked through the flattened sub-recipe graph). The
  generator calls it for any BALANCED slot template (strict BALANCED, and a MIX slot leaning
  balanced) **before** backtracking; a role with no candidate → the slot degrades to an
  explained unfilled entry. The result is an unsaved `Dish` carrying `_composed_recipes`;
  `persist` materialises it. `tag_limits` **is** applied: the composer skips a recipe whose
  own tags would breach the slot's remaining budget, and the generator decrements the budget
  for the composed dish's combined recipe tags (stashed on `_composed_tags`) exactly as for a
  real dish — a budget-blocked role degrades to an unfilled entry with a tag-limit reason.
  `favorites_bias` is not applied (a composed dish has no `DishStats`); `max_total_minutes`
  is, against the trio.
  *Reviewer-finding rework (2026-09-06):* composed dishes are now **deduplicated within a
  plan**. `compose_balanced_dish` takes `forbidden_signatures` (the recipe-id trios already
  placed) and returns `None` for a repeat → the surplus BALANCED slots go honestly unfilled
  instead of `save_plan` collapsing five identical dinners onto one `Dish` row.
  `generate._last_undoable` now skips composed slots (never worth backtracking past — undoing
  one only re-derives the same trio), which also drops the wasted-backtrack budget the old
  code burned (BACKLOG "Performance" item, now closed). Tests: `test_compose.py`
  `test_composed_dishes_within_one_plan_are_distinct`, reworked
  `test_composes_protein_carb_vegetable` / `test_composed_dish_persisted_on_save`.

- [x] **08.6 — Plan persistence**
  Save a previewed plan atomically, persisting composed dishes only on save.
  *Files:* `planner/services/persist.py`
  *Landed:* `save_plan` is `@transaction.atomic`; `build_profile_snapshot` is rebuilt from
  the live profile on every save (never the model's `{}` default), storing exclusion *names*
  so the snapshot still reads after a tag/ingredient is deleted. Two entries that composed
  the identical recipe trio share one persisted `Dish`.

- [x] **08.7 — Regeneration**
  Respect `is_locked`, consume locked entries' tag budget, accept a new seed.
  *Files:* `planner/services/generate.py`
  *Landed:* `regenerate_plan(plan, *, seed=None)` reads the plan's locked entries, derives
  slots from the snapshot, and re-runs `generate_plan` with them as `locked=` (deleted
  profile → `PlannerError`). Carried-forward findings:
  - locked-entry tags now fetched in **one batched query** (`missing_locked_ids`), not one per
    entry.
  - `bias = float(profile.favorites_bias)` is **kept** — the finding's premise is wrong:
    `random.choices` sums weights against `0.0` and raises `TypeError` on `Decimal`
    (verified, CPython 3.13), so the weight list must be float. Comment updated to say so.
  - `test_backtracking_path_is_deterministic` added — forces backtracking, asserts two
    same-seed runs are byte-identical (entries, unfilled, reasons, backtrack count).
  - `test-plan.md` `test_no_duplicate_dishes_within_plan` row reworded.
  - `test_pool_query_count` cap tightened `< 30` → `<= 14` (observed 10).

- [x] **08.8 — Shopping list integration**
  Orchestrate task 07's `populate_shopping_list`. **No new flattening or aggregation logic
  belongs here** — if it seems necessary, it belongs in 05/06/07.
  *Files:* `planner/services/shopping.py`
  *Landed:* `generate_shopping_list(plan)` / `preview_shopping_list(plan)` are pure
  orchestration. The read-only compute path was factored out of task 07's
  `populate_shopping_list` into `lists.services._flatten_dishes_to_lines` +
  `preview_shopping_list` (a behaviour-preserving extraction, one file) so preview and write
  share one code path — no flatten/aggregate/scale logic lives in `planner/`.

- [x] **08.9 — Serializers**
  Profile, plan, entry, `PlanResult`, and the generate-request serializer.
  *Files:* `planner/serializers.py`
  *Landed:* `MealPlanProfileSerializer` (not an `OwnedSerializer` — a profile is not an
  `OwnedModel`; `owner` injected from the request, `excluded_ingredients` scoped to
  `visible_to`), `MealPlanEntrySerializer`, `MealPlanSerializer` (`OwnedSerializer`;
  `profile` / `profile_snapshot` / `seed` read-only), `PlanResultSerializer`,
  `GeneratePreviewSerializer` / `PersistPlanSerializer` /
  `RegeneratePlanSerializer` / `RerollEntrySerializer` / `ShoppingListActionSerializer` /
  `ShoppingPreviewSerializer`. Carried-forward findings, all resolved:
  - `slots` non-empty enforced in `MealPlanProfileSerializer.validate_slots` (re-runs the
    model `validate_slots`).
  - `MealPlanEntrySerializer` filters `dish` through `Dish.objects.visible_to(request.user)`
    on write; `dish_name` reads `null` for a dish the viewer cannot see (page-wide
    `_visible_dish_ids` cache, tombstone like `ListItemSerializer`). A shared plan no longer
    leaks invisible dish names — pinned by `test_shared_plan_hides_invisible_dish_names`.
  - `favorites_bias = 0` 500: **fixed in the generator**, not the serializer —
    `_weighted_pick` falls back to a uniform draw when every candidate weight sums to zero
    (protects the admin / ORM / fixture paths too, not just the API).
  - `_state_before` guards `used.add(dish.pk)` with `if dish.pk is not None`.
  - `lists/services._flatten_dishes_to_lines` stale `viewer` comment reworded to `actor`.
  - `test_favorites_bias_increases_selection_rate` tightened to `> 0.44`.
  *Reviewer-finding rework (2026-09-06):*
  - **`MealPlan.days` unbounded on PATCH** — `MealPlanSerializer.days` is now an explicit
    `IntegerField(min_value=1, max_value=MAX_DAYS)`, and the model gained
    `MinValueValidator(1)` / `MaxValueValidator(7)` + a `planner_mealplan_days_range`
    `CheckConstraint` (migration `0003`), matching `MealPlanProfile.days`. A
    `PATCH {"days": 32767}` is now a 400, not tens of thousands of entry rows.
  - `regenerate_plan` with no explicit seed now **draws a fresh random seed** (aligned with
    `reroll_entry` and the 08.15 decision note); pass the plan's own seed to rebuild a week.
  - Dead `UnfilledSlotSerializer` deleted; `PlanResultSerializer.get_unfilled` uses
    `zip(strict=True)`; the duplicated `_snapshot_slots` is now the single public
    `persist.snapshot_slots`; `candidates._collect_recipe_ingredient_ids` promoted to public
    `collect_recipe_ingredient_ids`.
  - `test_security.py` gained IDOR rows for `entries/<id>/` PATCH and reroll by a read-only
    sharee, and an unauthenticated-request assertion in `test_profile_is_private_to_owner`.

- [x] **08.10 — API viewsets**
  Profiles, plans, generate-preview, persist, regenerate, entry patch, reroll, shopping-list
  generate and preview.
  *Files:* `planner/api.py`, `planner/api_urls.py`, `config/urls.py`
  *Landed:* `MealPlanProfileViewSet` (queryset scoped `owner=request.user` — no visibility
  model on a profile) and `MealPlanViewSet` (`OwnedViewSetMixin`). Routes:
  `POST /api/planner/plans/generate/` (preview), `POST /api/planner/plans/` (persist —
  regenerated deterministically from the seed), `POST .../<id>/regenerate/`,
  `PATCH .../<id>/entries/<entry_id>/`, `POST .../<id>/entries/<entry_id>/reroll/`,
  `POST .../<id>/generate-shopping-list/`, `GET .../<id>/preview-shopping-list/`.
  Carried-forward findings, all resolved:
  - `profile.owner == request.user` is structural: `GeneratePreviewSerializer.profile` /
    `PersistPlanSerializer.profile` / `RerollEntrySerializer` all resolve `profile` through
    `MealPlanProfile.objects.filter(owner=request.user)`, so another user's id is a 400.
  - Deleted-profile regenerate: `regenerate_plan` raises `PlannerError` → the endpoint
    catches it and returns a 400 (`{"detail": ...}`), never a 500. Same for `reroll`.
  - `days` passed explicitly to `generate_plan` **and** `save_plan` on persist;
    `persist.reconcile_entries(plan, days=, slots=)` runs on a `PATCH` that changes `days`
    (adds unfilled cells for new days, drops entries beyond the new range — the confirmation
    is the caller's).
  - `MealPlanSerializer.shopping_list` queryset constrained to `List.objects.filter(
    owner=request.user)`; `preview-shopping-list` is additionally owner-only (a shared-plan
    recipient would otherwise get the owner's ingredient list).
  - `persist.update_plan_in_place(plan, result, *, seed=None)` is `regenerate_plan`'s
    persistence partner — replaces unlocked entries on the existing `MealPlan`, never
    `create()`s a second one.
  - `MealPlanEntry.note` is carried: `generate._build_result` now copies the note from the
    locked source entry, and `update_plan_in_place` leaves locked rows completely untouched.

- [x] **08.11 — Profile editor UI**
  The eight gears grouped into four sections with sensible defaults.
  *Files:* `planner/views.py`, `planner/urls.py`, `planner/models.py` (`get_absolute_url`),
  `templates/planner/profile_form.html`, `templates/planner/profile_list.html`,
  `templates/planner/profile_confirm_delete.html`
  *Landed:* `MealPlanProfileForm` (`slots` exposed as a checkbox group over the JSON list;
  `tag_limits` stays a raw JSON field; `excluded_ingredients` scoped to `visible_to`), with a
  `grouped()` helper that arranges the bound fields into *When* / *What* / *Limits* /
  *Quality* (+ a *Shopping list* group for `exclude_staples`, which is not one of the eight
  gears). `ProfileListView` / `ProfileCreateView` / `ProfileUpdateView` / `ProfileDeleteView`,
  all scoped to `owner=request.user`, at `/planner/profiles/`. Setting a second default clears
  the first (the partial unique constraint would otherwise 500). The generate screen and the
  plan grid are 08.12.

- [x] **08.12 — Generate and plan grid UI**
  Week grid on desktop, stacked on mobile; lock, re-roll, and manual swap per slot; unfilled
  slots showing their reason inline.
  *Files:* `templates/planner/plan_detail.html`, `_partials/_slot_card.html`
  *Landed:* `PlanIndexView` (`/planner/`), `PlanGenerateView` (`/planner/plans/new/` — form +
  unsaved preview grid), `PlanSaveView` (stateless persist), `PlanDetailView`
  (`/planner/plans/<pk>/`), and per-slot HTMX views `entry-lock` / `entry-reroll` /
  `entry-swap` (each returns just the re-rendered `_slot_card.html`, targeted by
  `id="slot-<pk>"`), plus `PlanRegenerateView` and `PlanDaysView`. All write paths go through
  `_owned_plan()` (visible_to + owner-for-writes); `PlanDetailView` uses `OwnedObjectMixin`.
  Templates: `plan_index.html`, `plan_generate.html`, `plan_detail.html`, `days_confirm.html`,
  `_partials/{_plan_grid,_slot_card,_empty_pool,_shopping_preview,_days_confirm}.html`, plus a
  `.plan-grid` mobile-first CSS block in `components.css`. `MealPlan.get_absolute_url` added.
  Carried findings, all resolved:
  - **Meal-order sort** — `_slot_sort_key` orders cells breakfast → lunch → dinner in the grid
    (and `MealPlanEntrySerializer` already did the same for the API); model default untouched.
  - **`_slot_reason` wording** — now names the missing role(s): "…you have no vegetable recipe
    to compose one" / "protein or carb". `roles_composable` bool replaced by `missing_roles`.
  - **Auto-composed marking** — `MealPlanEntrySerializer.is_auto_composed` added; the grid
    shows an "Auto-composed" tag on a transient-dish slot (preview) and on a saved plan's
    materialised composed dishes (detected by the `notes` stamp). The "save as a real Dish"
    action is saving the plan (persist materialises every composed dish).
  - **Seed round-trip** — the preview carries `seed` in a hidden field into the persist POST.
  - **`days`-change confirm** — `PlanDaysView` GET renders a D39 `#modal` (`_days_confirm.html`)
    that names how many slots would be dropped; the drop only happens on the confirmed POST.
  - **`tag_limits` widget** — deferred to `Plan/BACKLOG.md` (UI polish).
  *Carried-forward review finding (08.1–08.4 review):* `MealPlanEntry.Meta.ordering` is
  `["day_index", "slot"]`, which sorts slots alphabetically (BREAKFAST, DINNER, LUNCH), not
  chronologically. The grid needs to impose an explicit meal-order (breakfast → lunch →
  dinner → …) rather than relying on the model default.
  *Carried-forward note (08.5–08.8 dev run):* `generate._slot_reason`'s "too few
  protein / carb / vegetable recipes to compose one" string is what an unfilled BALANCED slot
  shows. Confirm the wording reads well inline when this UI surfaces it; also decide how a
  slot filled by an auto-composed (transient) dish is marked in the grid and given its
  "save as a real Dish" action (`design.md` UI section).
  *Carried-forward review finding (08.5–08.8 review):* `_slot_reason`'s BALANCED wording
  ("too few protein / carb / vegetable recipes to compose one") fires even when only *one*
  role pool is empty. Fold a "name the missing role(s)" tweak into the wording review above.
  *Carried-forward notes (08.9–08.11 dev run):*
  - **Seed round-trip.** The persist path is stateless — `POST /api/planner/plans/`
    re-generates deterministically from `{profile, start_date, seed, days}`. The generate
    screen **must** carry the `seed` from the preview response (`PlanResultSerializer.seed`)
    into the persist POST, or "save exactly what I previewed" silently breaks.
  - **Auto-composed dishes.** A composed slot serializes as `dish: null` with
    `dish_name: "<A + B + C>"`; `MealPlanEntrySerializer` exposes **no boolean** for
    "this is auto-composed". Add one to the serializer when this UI lands, then render the
    "save as a real Dish" affordance off it.
  - **`days`-change confirmation.** `persist.reconcile_entries()` treats a `PATCH` that
    changes `days` as the confirmation to drop entries past the new range. The grid must
    show the D39-style confirm page/modal **before** sending that PATCH.
  - **`tag_limits` widget.** `MealPlanProfileForm.tag_limits` is a raw JSON textarea. A
    per-tag widget (tag dropdown + number) is a reasonable polish pass here (or
    `Plan/BACKLOG.md` if it slips).

- [x] **08.13 — Shopping list preview and generation UI**
  Preview with a staples toggle, plus the task 07 warning when checked items would be replaced.
  *Files:* `templates/planner/_partials/_shopping_preview.html`
  *Landed:* `PlanShoppingPreviewView` (`GET …/shopping/preview/`, owner-only, returns the
  partial into `#shopping-preview` on the detail page) and `PlanShoppingGenerateView`
  (`POST …/shopping/generate/` → `planner.services.generate_shopping_list` → redirect to the
  list). The staples checkbox re-fetches the preview via `hx-get`; the task-07 warning fires
  when this plan already has checked `GENERATED` items on its linked list. No new
  flatten/aggregate logic — pure orchestration over `planner.services.shopping`.
  *Carried-forward note (08 wrap-up dev run):* `PlanShoppingPreviewView` now catches
  `(ListError, PlannerError)` and re-renders `_shopping_preview.html` inline with an
  `alert alert-warning` instead of 500ing when a planned dish became invisible between save
  and preview (was review finding 1). The inline message is task 07's raw service string
  ("One of the dishes in this plan is not available to you, so the shopping list cannot be
  built.") — reviewer should confirm that wording reads acceptably inline here.

- [x] **08.14 — Empty-state handling**
  A user with no dishes gets a clear explanation and a route forward, not a blank grid.
  *Files:* `templates/planner/_partials/_empty_pool.html`
  *Landed:* `_empty_pool.html` (links to create/browse dishes and to profiles) shows on the
  planner index and the generate screen for a user with no usable dishes, and on the generate
  screen when a generation pass fills **zero** slots (over-tight scope/constraints), carrying
  the generator's own reason string. `_grid_rows` never renders a blank grid — a POST that
  can fill nothing routes to the guidance instead.

- [x] **08.14a — Light up the "Planner" home card**
  `templates/core/_partials/_home_content.html` still renders Planner as a non-interactive
  "Coming soon." card (a task-02 placeholder; 04-07 wired up their own on the way through, 07
  via 07.13a). Turn it into an `<a class="card card-link" href="/planner/">` with a one-line
  description, matching the other cards. Update `core/tests/test_templates.py`
  `test_home_dashboard_cards` (no "Coming soon." cards should remain). The richer dashboard —
  this week's plan surfaced on the home page, active shopping list, recently viewed — is
  task 12, which is best done right after this task lands.
  *Files:* `templates/core/_partials/_home_content.html`, `core/tests/test_templates.py`

- [x] **08.16 — Dev-test rework (manual pass, 2026-09-07)**
  Fixes and additions from the human click-through (`dev-test-walkthrough.md`). The findings
  file this block was worked from (`.review-findings.md`) has been consumed and deleted per the
  pipeline contract; every owner decision and root cause it carried is folded into the B1–N6
  notes below and the decision-log entries under 08.15. Ran **before** 08.15's final wrap-up.
  *Blocking:*
  - B1 preview grid labels every dish "A dish shared privately" (`_slot_card.html` /
    `PlanGenerateView` — preview entries never get `dish_visible`, and the name is only linked
    in `saved` mode).
  - B2 single-slot reroll can duplicate another day's dish — `generate._state_before` only
    counts slots before the grid index, so locked entries after the rerolled slot don't
    reserve their dish. Fold all locked entries into the used-set / tag budget regardless of
    position.
  - B3 reroll re-picks the same dish / silent no-op — `reroll_entry` doesn't exclude the
    slot's own current dish; surface a message when nothing fits / nothing changed.
  - B4 "Leave out pantry staples" can't be unchecked — bare checkbox; unchecking reads as
    "unspecified" → profile default `True`. Tri-state it.
  - B5 `min_rating` — clamp blank→None / `<1`→1 / `>5`→5 in the form (no error); spinner
    `min=1 max=5`.
  - B6 `favorites_bias` — clamp `<1`→1 in the form; spinner `min=1`. No migration (model
    stays `>= 0` + generator zero-weight fallback).
  - B7 all-empty / heavily-unfilled saved plan has no explanation (walkthrough 6e + 10).
    **Owner decision: page-level reason banner on `PlanDetailView`, no schema change** — the
    persisted per-slot `reason` stays the `BACKLOG.md` item.
  - B8 no way to delete a plan — `PlanDeleteView` + confirm + button, plus multi-select
    delete on the planner index. Must not delete the linked shopping `List`.
  - B9 no way to share a plan (walkthrough 11). **Owner decision: add it now** — replicate the
    per-app `_ShareView` / `_share_modal` pattern for `MealPlan` (read-only-for-recipients is
    already enforced). Edit-share (11a) is a future task — no code this pass.
  *Non-blocking, this pass:* N1 whole plan/profile card clickable · N2 `tag_limits` per-row
  widget (closes the `BACKLOG.md` UI-polish item) · N3 `excluded_ingredients` checkbox list +
  search · N4 plan action-bar layout (owner picked a single aligned horizontal row) · N5
  generate-screen Days label (the field overrides the profile; blank = profile default) · N6
  Balanced-template explainer + `dev-test-walkthrough.md` Scenario 9 correction (**owner
  decision: keep strict Balanced, fix messaging** — the pool is correct, the template has no
  partial/one-pot fallback by design).
  *Recorded, no code:* excluded-tags only filters dish-level `Dish.tags` (an untagged or
  auto-composed dish survives "exclude every tag") — `design.md` clarification only;
  pantry-list feature → its own task (pointer in `BACKLOG.md`); a stray materialised
  "Turkey Meatballs + Skillet Cornbread + Almond Green Beans" dish on the dev box, to prune
  or re-seed before the next manual pass.
  *Files:* `planner/views.py`, `planner/urls.py`, `planner/services/generate.py`,
  `planner/services/persist.py`, `templates/planner/**`, `templates/planner/_partials/**`,
  `static/css/components.css`, `planner/tests/**`, `dev-test-walkthrough.md`.

- [x] **08.17 — Reviewer polish findings (post-08.16 review, 2026-09-07)**
  Three non-blocking findings from the 08.16 code review, flagged "fix now". Runs **before**
  08.15's final wrap-up. Each needs a test that fails on regression.
  - **F1 (blocking-quality — `design.md` conformance): `plan_detail.html` still renders the
    grid under the empty-pool guidance.** When `empty_pool` is true the page shows the
    `_empty_pool` guidance *and then* `{% include "planner/_partials/_plan_grid.html" %}`, so
    the owner gets the guidance followed by a wall of "Empty" cards. `design.md` ("Edge
    cases" / "UI") says an effectively-empty pool shows "the empty-state guidance instead of
    a wall of blank cards". Fix: wrap the grid include in `{% if not empty_pool %}`. Tighten
    `test_saved_plan_all_unfilled_shows_empty_pool_guidance` (`test_views.py`) to also assert
    `'class="plan-grid"' not in body`.
  - **F2 (parity): `PlanShareModalView.get` resolves via `visible_to`, not `_owned_plan`.**
    A read-only sharee can open the (non-functional) share modal — it renders without
    `shareable_users` and any submit still 403s via `share()`, so no security impact, but it
    is inconsistent with `PlanDeleteView` and the design's "Share / unshare are owner-only".
    Fix: use `_owned_plan` (or early `raise PermissionDenied` when
    `plan.owner_id != request.user.id`). Add a test that a sharee GET is 403/404.
  - **F3 (misleading message): `PlanEntryRerollView.post` "Nothing changed — no other dish
    fits this slot."** is only reachable when re-rolling an already-empty slot that stays
    empty (a successful `reroll_entry` cannot return the excluded current dish; a failed one
    raises `PlannerError`). It reads as a failure where the user deliberately re-rolled a
    blank slot. Fix: guard with `and before is not None`, or drop the branch (the
    `PlannerError` path already covers "nothing fits"). Adjust or add the covering test.
  *Files:* `templates/planner/plan_detail.html`, `planner/views.py`, `planner/tests/test_views.py`.
  *Landed (2026-09-07):* F1 — grid include in `plan_detail.html` now gated `{% if not empty_pool %}`
  (`empty_pool` is only ever truthy for the owner, so a sharee still always gets the grid). F2 —
  `PlanShareModalView.get` now resolves via `_owned_plan` (sharee GET → 403). F3 — the reroll
  "nothing changed" info branch is now guarded `before is not None and self.entry.dish_id == before`.
  Tests: tightened `test_saved_plan_all_unfilled_shows_empty_pool_guidance` (+`class="plan-grid"`
  absence); new `test_share_modal_forbidden_for_sharee`,
  `test_reroll_empty_slot_that_stays_empty_shows_no_misleading_message`.
  *Carried-forward parity note (fold into the 08.15 review, no code this pass unless the reviewer
  disagrees):* F2 fixed only the modal `GET`. `PlanShareView.post` / `PlanUnshareView.post` still
  resolve via `visible_to`, not `_owned_plan` — a sharee's submit is refused inside
  `share()` / `unshare()` by the actor check (403), so there is no security or behaviour gap, but
  the resolution path is still inconsistent with `PlanDeleteView`. Align them or accept the
  asymmetry explicitly.

- [x] **08.18 — Dev-test rework round 2 (manual pass, 2026-09-07)**
  Four findings B1–B4 from a second human click-through on `fedora-headless` (after 08.16 /
  08.17). Full owner words, root causes and per-item tests were in
  `Plan/08-Meal-Planner/.review-findings.md` — consumed and deleted per the pipeline contract.
  Runs **before** 08.15's wrap-up. All four are template / widget / view / CSS only — no model
  or migration change.
  - **B1 — plan-index select checkbox overlapped the card and was hard to press.** Root cause:
    `.card-select` was `position: absolute` inside the card's own padding box (on top of the
    title text) and lost the z-index tie to the stretched `a.card-link::after`. Fix: the
    `.card-selectable` card is now a flex row — the checkbox has its own leading `--tap-target`
    gutter (`.card-select`, `z-index: 2` above the stretched link) and the title + meta sit in
    a new `.card-selectable-body` wrapper (`plan_index.html`). Test:
    `test_views.py::test_selectable_plan_card_renders_checkbox_and_link` (both the `name="ids"`
    checkbox and the whole-card `a.card-link` survive; visual check noted for the manual pass).
  - **B2 — profile-form exclusion filter did nothing and Enter reloaded the page.** Root
    causes: the script keyed off `id_excluded_*` / `<li>` rows, but `CheckboxSelectMultiple`
    renders `<div>` rows (no `<li>`), so the filter matched nothing; and the injected
    `<input type="search">` lived inside `<form>`, so Enter submitted. Fix: `profile_form.html`
    now wraps both `excluded_tags` / `excluded_ingredients` in
    `<div class="checklist" data-checklist="…">`; the script binds to that hook, toggles each
    checkbox's own wrapper (`box.closest("div")`), and `preventDefault`s Enter in the filter.
    Still progressive — no JS leaves the plain checkbox list. Tests:
    `test_views.py::test_profile_form_exclusion_lists_are_filterable` (markup contract for both
    fields) + the existing `test_profile_form_excluded_ingredients_render_as_checkboxes` still
    green.
  - **B3 — tag-limits widget: default 5 rows → 3, add per-row remove buttons.** Owner decision:
    allow removing down to **zero** rows (an all-blank set already serialises to `{}`, and
    `value_from_datadict`'s `zip(strict=False)` + blank-skip needs no server change). Fix:
    `TagLimitsWidget.MIN_ROWS = 3`; `_row` renders a `data-tag-limits-remove` button (hidden
    until the profile-form script reveals it and wires the click to `row.remove()`); the
    `<template>` clone carries it too. Tests:
    `test_views.py::test_tag_limits_widget_defaults_to_three_rows`,
    `test_tag_limits_widget_render_includes_remove_control`,
    `test_tag_limits_fewer_rows_than_default_still_saves`. No existing N2 test hard-coded a
    5-row count (they assert specific option values), so none needed the row-count fix the
    findings file anticipated.
  - **B4 — no HTML way to rename a `MealPlan` after creation.** Fix: `PlanRenameView`
    (`GET` renders a tiny form — `#modal` fragment for HTMX, full page otherwise; `POST` writes
    `name` and redirects back), owner-only via `_owned_plan` (sharee → 403). Route
    `planner:plan-rename`; templates `planner/plan_rename.html` + `_partials/_plan_rename.html`;
    a **Rename** button added to the `plan_detail.html` owner action bar next to Share / Delete.
    Owner decision on the blank-name rule: **allow blank and trim**, matching the generate flow
    — a cleared name renders as "Meal plan" / "Untitled plan". Tests:
    `test_views.py::test_rename_plan_owner_only`, `test_rename_plan_blank_name`;
    `test_security.py::test_plan_rename_is_owner_only` (another user's private plan → 404,
    shared → 403, name unchanged).
  *Files:* `planner/views.py`, `planner/urls.py`, `static/css/components.css`,
  `templates/planner/plan_index.html`, `templates/planner/profile_form.html`,
  `templates/planner/plan_detail.html`, `templates/planner/plan_rename.html`,
  `templates/planner/_partials/_plan_rename.html`, `planner/tests/test_views.py`,
  `planner/tests/test_security.py`, `Plan/08-Meal-Planner/dev-test-walkthrough.md`.
  *Landed (2026-09-07):* all four fixed; `.review-findings.md` deleted. Full `uv run pytest`
  green (1036 passed / 1 skipped), `ruff check` + `ruff format` clean,
  `makemigrations --check` clean.

- [x] **08.19 — Reviewer polish findings (post-08.18 review, 2026-09-07)**
  Three non-blocking "fix now" findings from the post-08.18 p2p-reviewer pass (verdict:
  APPROVE — none are blocking). All small and low-risk. Runs **before** 08.15's wrap-up.
  Each code fix needs a test that fails on regression.
  - **R1 — `persist.reroll_entry` runs the generator inside its own write transaction.**
    `planner/services/persist.py` (~lines 204–260): `reroll_entry` is `@transaction.atomic`
    and calls `generate_plan()` (~10+ SELECTs plus bounded backtracking) while holding the
    `transaction_mode="IMMEDIATE"` write lock. The API `regenerate` path deliberately does
    the opposite — `regenerate_plan()` runs outside any transaction and only
    `update_plan_in_place()` is atomic. Violates ARCHITECTURE §2 "never hold a write
    transaction across a slow loop". Fix: build the `PlanResult` before
    `with transaction.atomic():` in `reroll_entry`, mirroring `regenerate`. Add/adjust a test
    asserting generation happens outside the atomic block (e.g. the reroll path issues its
    reads before `BEGIN IMMEDIATE`, or a narrower unit assertion on call ordering).
  - **R2 — `PlanShareView.post` / `PlanUnshareView.post` resolve via `visible_to`, not
    `_owned_plan`.** `planner/views.py` (~lines 1022–1044). Functionally safe today —
    `core.services.sharing.share/unshare` raise `PermissionDenied` for a non-owner actor and
    these views do not catch it, so a sharee gets a real 403 (`test_plan_share_is_owner_only`
    passes) — but the resolution path is inconsistent with `PlanDeleteView` /
    `PlanRenameView` / `PlanShareModalView`, all of which use `_owned_plan`, and with
    CLAUDE.md §6 ("never hand-roll an ownership filter in a view"). Fix: one-line swap to
    `_owned_plan` in both views. **This resolves the 08.17 carried-forward parity note**
    (F2's "modal GET fixed, POST still on `visible_to`"). Add a test that a sharee's
    share/unshare POST is 403/404 (distinct from the existing owner-only test).
  - **R3 — `import random` inside `PlanGenerateView.post`.** `planner/views.py` (~line 512).
    The other random draws in the file's service layer import at module scope. Cosmetic —
    move to a module-level import. Covered by existing generate tests; no new test needed.
  *Files:* `planner/services/persist.py`, `planner/views.py`, `planner/tests/` (test_persist,
  test_security or test_views).
  *Landed (2026-09-07):* R1 — `reroll_entry` is no longer `@transaction.atomic`; it builds
  the `PlanResult` first and only the entry write / composed-dish materialisation run inside
  a `with transaction.atomic()` block (mirrors `regenerate_plan`). R2 — `PlanShareView.post`
  / `PlanUnshareView.post` resolve through `_owned_plan` (non-owner who cannot see the plan →
  404, sharee → 403), closing the 08.17 carried parity note. R3 — `import random` moved to
  module scope in `planner/views.py`. Tests:
  `test_persist.py::test_reroll_runs_the_generator_outside_a_write_transaction`
  (`django_db(transaction=True)` — asserts the generator runs with the connection not in an
  atomic block), `test_security.py::test_plan_share_post_resolves_through_owned_plan`.

- [x] **08.20 — Dev-test rework round 3 (manual pass, 2026-09-07)**
  Three findings B1–B3 from a third human click-through on `fedora-headless`, sharing a saved
  plan from `hamon` to `avi`. Full owner words, root causes and per-item tests are in
  `Plan/08-Meal-Planner/.review-findings.md` — the dev works that file and deletes it. Also
  folds in the still-open **08.19** reviewer-polish findings (R1–R3), since the dev is already
  in those files. Runs **before** 08.15's wrap-up.
  - **B1 — sharing a plan does not cascade read-grants to its dishes/recipes.** Owner decision:
    cascade exactly like `Dish` sharing — `MealPlan.share_dependencies()` returns the entries'
    distinct dishes, `walk_dependencies` pulls the rest; same refuse-if-ungrantable rule.
    Reverses D44's cascade clause (decision-log write-up deferred to 08.15). Re-decide
    `contains_owned_children`; `copy_children` stays a documented no-op.
  - **B2 — a plan shared with you never shows in your planner index.**
    `PlanIndexView` filters `owner=user`. Add a separate "Shared with you" section outside the
    owner-only bulk-delete form.
  - **B3 — no ownership badge in the planner, and the Lists index lacks it too.** Wire the
    existing `_ownership_badge.html` into the planner pages and audit every owned-object index
    page, adding it where missing.
  *Files:* `planner/models.py`, `planner/views.py`, `planner/services/persist.py`,
  `templates/planner/**`, `templates/lists/**`, `planner/tests/**`, `lists/tests/**`.
  *Deferred, recorded in `Plan/13-Collaborative-Sharing/design.md` (no code this pass):*
  make-public UI discoverability; sort/filter a list page by access type; the whole
  sharing-model rework (household/group concept, edit access) the owner wants designed in a
  planning session.
  *Landed (2026-09-07):* B1 — `MealPlan.share_dependencies()` returns the entries' distinct
  dishes; `walk_dependencies` pulls each dish's recipe graph, and
  `core.services.sharing._validate_cascade` gives the refuse-if-ungrantable behaviour for
  free. `contains_owned_children = False` removed (back to `None`); both `share_dependencies`
  and `copy_children` are now overridden (`copy_children` a documented no-op — plan copy is
  out of scope, `MealPlanViewSet.copy` is 405), so `core/tests/test_conventions.py` stays
  green. Model docstring rewritten to describe the cascade posture (ARCHITECTURE.md
  decision-log write-up left to 08.15 as instructed). B2 — `PlanIndexView` adds
  `shared_plans` (`visible_to(user).exclude(owner=user)`); `plan_index.html` renders a
  "Shared with you" section **outside** both the has-dishes/has-profile gate and the
  owner-only bulk-delete `<form>` (a sharee with no dishes/profile of their own must still
  reach a shared plan). B3 — `_ownership_badge.html` wired into `plan_index.html` (both
  sections) and `plan_detail.html` (next to the heading). Index-page audit: recipe / dish /
  book / ingredient indexes render the badge via their `_*_results.html` partials, and the
  Lists index via `_list_index.html:29` — all already present since task 07; the planner was
  the only gap. Tests: `test_models.py::test_plan_share_dependencies_are_its_scheduled_dishes`;
  `test_security.py::test_sharing_a_plan_cascades_read_to_its_dishes_and_recipes`,
  `test_sharing_a_plan_with_an_ungrantable_dish_is_refused`,
  `test_unsharing_a_plan_does_not_revoke_the_cascaded_dish_grants`;
  `test_views.py::test_shared_plan_appears_in_sharees_planner_index`,
  `test_owner_still_sees_own_plans_with_bulk_delete`,
  `test_invisible_plan_appears_in_neither_section`,
  `test_planner_index_shows_ownership_badges`,
  `test_plan_detail_shows_ownership_badge_for_sharee`;
  `lists/tests/test_views.py::test_list_index_shows_ownership_badges`.
  `.review-findings.md` consumed and deleted per the pipeline contract.

- [x] **08.15 — Update the living document**
  Task 08 → AWAITING APPROVAL → COMPLETE (owner-approved 2026-09-07). Resolved the
  `MealPlan`-vs-`List` open question (`ARCHITECTURE.md` §7): `MealPlan` stays a distinct model
  that *generates* a `List`; it is never rendered as a `kind=MEAL_PLAN` list. The generated
  shopping list is a separately-owned, separately-shared `List`, and deleting a plan removes
  its entries but not that list.
  *Landed (2026-09-07):* `MILESTONES.md` task-08 row rewritten and status → COMPLETE;
  decision-log entries D44 (amended), D47–D50 added to `ARCHITECTURE.md`; `ARCHITECTURE.md` §5
  gear-8 semantics + `exclude_staples` acknowledgement noted; §7 open question struck;
  stale `.review-findings.md` pointers in this file and `test-plan.md` re-pointed.
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`
  *Carried-forward doc cleanup (08.16 rework, 2026-09-07):* `.review-findings.md` has been
  consumed and deleted per the pipeline contract, but `tasks.md` (this 08.16 block) and
  `test-plan.md` (the "Dev-test rework (2026-09-07)" heading, ~line 161) still point at it for
  "full context / root causes / owner decisions". Re-point or drop those two references while
  updating the living docs — the owner decisions they cite are already folded into the 08.16
  `tasks.md` block and the decision-log notes above.
  *Carried-forward review findings (08.1–08.4 review) — fold into the `ARCHITECTURE.md`
  decision-log update at task completion:*
  - `design.md` was edited on this branch: `source_scope` default `MINE_AND_SHARED` → `SHARED`
    (cosmetic enum rename, semantics match ARCHITECTURE §5 gear 3) and the `MIX` template was
    expanded to describe per-slot BALANCED/ONE_POT alternation (a genuine refinement). The
    `MIX` semantics **and** the strict-BALANCED "no dish-level fallback" behaviour should land
    in the decision log, not only in `design.md` + code comments.
  - **The D44 re-decision landed in 08.20 B1 — record it in the decision log.** Task 08
    *reverses* D44's non-cascade clause: sharing a `MealPlan` **cascades** read-grants to its
    scheduled dishes and their recipe graphs, exactly like sharing a `Dish`
    (`MealPlan.share_dependencies()` → the entries' distinct dishes → `walk_dependencies`),
    with the same refuse-if-a-dependency-can't-be-granted rule. `contains_owned_children` is
    back to `None` (the line was removed); both `share_dependencies` and `copy_children` are
    overridden, `copy_children` a deliberate no-op (plan copy stays out of scope,
    `MealPlanViewSet.copy` is 405). The generated `shopping_list` is **not** a share
    dependency. The model docstring and `design.md`'s "Security notes" now describe this;
    ARCHITECTURE.md D44 still needs the struck-through-and-noted update.
    *Depth-budget note (08.20 dev run):* `walk_dependencies` caps at `MAX_DEPTH = 5`. Rooting
    the walk at the plan adds one level above each dish, so a plan share over a near-maximal
    recipe graph (dish → recipe → sub → sub → sub) can raise `DepthExceededError` where
    sharing that same dish directly would still pass. `share()` turns `GraphError` into a
    user-facing refusal (not a 500), and real recipe nesting is shallow, so this is a latent
    asymmetry, not a live bug — pin it in the decision log or accept it explicitly.
  - *(08 review, 2026-09-06)* When recording the D44 sharing posture, note the accepted
    tombstoning boundary: `MealPlanEntrySerializer` nulls `dish_name` for a dish the viewer
    cannot see but still returns the raw integer `dish` id (still reachable when a dish is
    unshared *after* the plan was shared, even though a fresh cascade now makes every
    scheduled dish visible). This is **consistent with the
    reviewed task-07 `ListItemSerializer` pattern** (plain `PrimaryKeyRelatedField` +
    tombstoned `_name`); the id is not dereferenceable (`/api/meals/dishes/<id>/` is
    `visible_to`-scoped → 404) and the threat model is 10-20 trusted users. Accepted as-is.
  - `MealPlanProfile.exclude_staples` is a de-facto 9th knob (a shopping-list rendering
    option, not one of "the eight gears"). Acknowledge it against the "eight gears, capped"
    invariant in ARCHITECTURE §5 so it is not later read as a violation.
  - (08.5–08.8 dev run) `design.md` says 08.8 "only orchestrates" and no read-only preview
    primitive existed in task 07 (`populate_shopping_list` always writes). The dev extracted
    task 07's compute path into `lists.services._flatten_dishes_to_lines` +
    `preview_shopping_list(owner, dishes, *, exclude_staples)` (behaviour-preserving; one
    file) so `planner/` stays pure orchestration and preview/write share one path. Record
    this as the accepted resolution of the "orchestrates only" constraint.
  - (08.5–08.8 dev run) `profile_snapshot` as built by `persist.build_profile_snapshot`
    stores the gears **plus `profile_id`** and stores exclusion *names* (not FKs) so it still
    reads after a tag/ingredient is deleted. Note the actual snapshot shape in the decision
    log.
  *Carried-forward review finding (08.9–08.11 review) — CODE FIX LANDED, still needs the
  decision-log write-up:* `MealPlanSerializer` exposed `profile_snapshot` to every reader of a
  plan, handing a `SHARED` / `PUBLIC` plan's readers the owner's `excluded_ingredients`
  (allergy list), `excluded_tags`, `tag_limits` and profile name. Fixed in the 08.9–08.11
  rework pass: `MealPlanSerializer.profile_snapshot` is now a `SerializerMethodField` returning
  `{}` for anyone but the owner (D35 pattern), and `plan_detail.html` gates the profile name on
  `is_owner`. 08.15 must still fold this into the D44 sharing-posture write-up in the decision
  log (the snapshot is owner-only on read, same as `shared_with`).
  *Carried-forward review finding (08 review rework, 2026-09-06) — CODE FIX LANDED, needs a
  decision-log line:* the inherited `copy` action (`OwnedViewSetMixin`) transferred plan
  ownership to the copier, which flipped `get_profile_snapshot` open and handed out a live
  `profile` FK into the owner's private `MealPlanProfile`. `MealPlanViewSet.copy` now overrides
  it to `405 MethodNotAllowed` (route kept for discoverability; permission layer still 404s a
  non-visible plan first). Record alongside the D44 posture: plan-copy is out of scope (D44),
  and `share` / `unshare` / `shares` stay available and safe (they never change `owner_id`, so
  the snapshot stays `{}` for a sharee). A real plan-copy would need a `copy_children` hook
  that deep-copies entries and resets `profile` / `shopping_list` / `profile_snapshot`.
  *Carried-forward review finding (08 wrap-up dev run) — decision-log one-liner:* a cleared
  `no_repeat_days` on `MealPlanProfileForm` now falls back to the design default (14, via the
  new `planner.models.DEFAULT_NO_REPEAT_DAYS` constant) rather than coercing to 0, and an
  **explicit** `0` is preserved as a deliberate "no window" choice. Record this cleared-gear
  fallback (and that `0` is a valid disable value) in the decision log.
  *Carried-forward note (08.9–08.11 rework, locked-empty fix):* `regenerate_plan` now carries
  a locked-but-empty slot (`is_locked=True, dish=None`) through as `locked` and `_build_result`
  no longer reports it as unfilled — so a deliberately locked-empty slot does not add to a
  plan's "N slots still open" count. This matches locked-filled semantics but is not discussed
  in `design.md` / `test-plan.md`; add a one-liner to the decision log if it wants pinning.
  - (08.5–08.8 dev run) Generator behaviour to record: composition is attempted for any
    BALANCED-leaning slot (strict `BALANCED`, and a `MIX` slot leaning balanced) **before**
    backtracking; a `MIX` one-pot-lean and `ONE_POT` slot keep an any-dish fallback.
    Backtracking past a composed slot re-composes (a transient dish has no pk for the `tried`
    set) — bounded by `MAX_BACKTRACKS` and deterministic under seed.
  - (08.12 dev run) **Composed-dish distinctness.** `design.md`'s composition section did not
    anticipate the "a plan never repeats a dish" requirement colliding with a small recipe
    library. Resolved per the 08.1–08.11 reviewer's suggestion: `compose_balanced_dish`
    refuses a recipe-trio whose signature is already placed in the plan
    (`forbidden_signatures`), so a thin library composes **one** BALANCED dinner and leaves
    the surplus slots honestly unfilled rather than repeating it (and `_last_undoable` skips
    composed slots, which also removed the wasted-backtrack budget the reviewer flagged).
    Record the degrade-not-repeat behaviour in the decision log.
  - (08.12 dev run) **Generate → persist is a stateless HTML flow too** — the same accepted
    deviation already recorded for the API persist route: the preview grid carries
    `{profile, start_date, seed, days}` in hidden fields into `PlanSaveView`, which re-runs
    the deterministic generator and saves. No server-side preview storage on the HTML path
    either.
  - (08.12 dev run) **Saved-plan unfilled slots show a generic line**, not the generator's
    original reason — `MealPlanEntry` has no field to persist the reason (see
    `Plan/BACKLOG.md` → Meal planner follow-ups). The live preview grid shows the full reason
    inline; a saved empty slot is still re-rollable.
  *Carried-forward deviations from `design.md` (08.9–08.11 dev run) — decision-log entries:*
  - **Persist is stateless.** `POST /api/planner/plans/` does not store previews — it
    re-runs the generator from `{profile, start_date, seed, days}` and saves. C9 determinism
    guarantees byte-identical output; `PlanResultSerializer` returns `seed` for the client to
    echo back. The persist request body carries `days` and `name` (the design's API table
    lists no body for that route).
  - **`preview-shopping-list` is owner-only**, not `IsOwnerOrReadOnly` — otherwise a
    shared-plan recipient could pull the owner's aggregated ingredient list.
  - **`regenerate` / `reroll` draw a fresh random seed** each call.
  - **`favorites_bias = 0` fix chose the generator, not the serializer:** `_weighted_pick`
    falls back to a uniform draw when the weight list sums to zero, so every path (admin,
    fixtures, direct ORM) is protected, not only the API.
  - *(08 review, 2026-09-06)* **Regenerate keeps a locked slot's note, drops an unlocked
    slot's note.** `persist.update_plan_in_place` writes `row.note = entry.note` for unlocked
    rows and `_build_result` gives a rolled slot `note=""`, so a note typed on an unlocked
    slot is wiped when the plan is regenerated. Intentional (regeneration replaces the slot);
    record it so it is not later read as data loss.
  - *(08 review, 2026-09-06)* **Gear-8 time budget is `max(prep) + sum(cook)`, not a plain
    sum.** `meals/services/dishes.total_minutes_for` (used by `build_candidate_pool` and
    `compose`) models a cook prepping in parallel, so it diverges from `design.md` gear 8's
    "prep + cook budget per meal" shorthand. Already documented in that function; note the
    accepted reading in the decision log.
  - *(dev-test rework, 2026-09-07 — 08.16)* Decision-log lines:
    - **Plan sharing UI shipped** (walkthrough finding 11). Owner-approved. Uses the same
      `shared_with` M2M and read-only-recipient posture as dishes/lists; edit-share is
      deferred to the future edit-share task (11a). **Superseded by 08.20 B1:** sharing a plan
      now *cascades* to its scheduled dishes (like `Dish` sharing), `contains_owned_children`
      is back to `None`, and both hooks are overridden — see the 08.20 note above.
    - **Plan delete UI shipped** (single + multi-select). Deleting a plan cascades its
      entries but never its generated shopping `List` (a separately-owned object, D44).
    - **Strict BALANCED confirmed by owner** — no fallback to a partial / one-pot dish; an
      unmet BALANCED slot composes from recipes, else goes explained-unfilled. Non-P/C/V
      shared/public dishes surface only under One-pot / Mix. Messaging added, not behaviour.
    - **Saved-plan unfilled slots** now get a page-level reason banner recomputed from the
      plan's own seed; the per-slot persisted `reason` field remains a `BACKLOG.md` item.
    - **Excluded-tags filters dish-level `Dish.tags` only** — an untagged or auto-composed
      dish is not caught by "exclude every tag". Accepted; recipe-level tag exclusion would
      be a separate task.
    - **`MealPlan.name` is `blank=True`, not the required field `design.md` specifies**
      (`name = models.CharField(max_length=200)`). Owner's 08.18 B4 decision ("allow blank
      and trim") — a cleared name renders as "Meal plan" / "Untitled plan", matching the
      generate flow. Already implemented and tested; record the deviation in the decision log.
      *(post-08.18 review, 2026-09-07.)*

  > **Then tell the owner, explicitly, that [task 12 — Home Dashboard](../12-Home-Dashboard/design.md)
  > is the next task to run.** It is the only task gated on 08 finishing rather than on the
  > numbered chain: its two headline panels (this week's plan, the active shopping list) need
  > tasks 07 and 08 to exist, and it replaces the placeholder card grid 08.14a just finished
  > patching. Do not let it drift to the end of the project — say it out loud at handoff.
