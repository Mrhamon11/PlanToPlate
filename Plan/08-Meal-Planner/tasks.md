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
  - *(08 review, 2026-09-06)* When recording the D44 sharing posture, note the accepted
    tombstoning boundary: `MealPlanEntrySerializer` nulls `dish_name` for a dish the viewer
    cannot see but still returns the raw integer `dish` id. This is **consistent with the
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

  > **Then tell the owner, explicitly, that [task 12 — Home Dashboard](../12-Home-Dashboard/design.md)
  > is the next task to run.** It is the only task gated on 08 finishing rather than on the
  > numbered chain: its two headline panels (this week's plan, the active shopping list) need
  > tasks 07 and 08 to exist, and it replaces the placeholder card grid 08.14a just finished
  > patching. Do not let it drift to the end of the project — say it out loud at handoff.
