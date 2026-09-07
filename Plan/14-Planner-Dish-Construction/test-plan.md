# 14 — Planner Dish Construction · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Tests that would fail if the behaviour regressed — not tests that merely execute code.

## Models — `planner/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_profile_construction_gear_defaults` | `allow_dish_construction` defaults `False`, `construction_slots` `0`. |
| `test_profile_construction_slots_range` | `construction_slots > MAX_DAYS` fails validation; `0` and `7` pass. |
| `test_entry_dish_and_composed_are_exclusive` | An entry with both `dish` set and `composed_recipe_ids` non-empty raises `ValidationError`. |
| `test_entry_composed_defaults_empty` | A plain entry has `composed_recipe_ids == []`, `composed_name == ""`. |
| `test_snapshot_records_construction_gear` | `build_profile_snapshot` carries `allow_dish_construction` and `construction_slots`. |

## Composition — `planner/tests/test_compose.py`

| Test | Asserts |
|---|---|
| `test_one_pot_pool_is_visible_to_only` | `build_one_pot_recipe_pool` never returns a recipe the user cannot see. |
| `test_one_pot_pool_excludes_excluded_tag_and_ingredient` | Same exclusion filtering as the P/C/V pools, ingredients checked through the sub-recipe graph. |
| `test_compose_one_pot_picks_one_pot_role` | The composed dish's single component is an `ONE_POT`-role recipe. |
| `test_compose_one_pot_none_when_no_recipe` | Empty pool → `None`, not an exception. |
| `test_compose_one_pot_respects_forbidden_signature` | A single-recipe signature already placed → `None`. |
| `test_compose_one_pot_respects_time_budget` | Over `max_total_minutes` → `None`. |
| `test_transient_dish_from_ids_round_trips` | Ids → unsaved `Dish` with `_composed_recipes` in order, `_is_composed` true, `pk is None`. |
| `test_single_shot_forbidden_signature` *(BACKLOG check)* | Either fixed (bounded retry finds a distinct valid trio) or the BACKLOG line is confirmed still standing — dev's call, recorded. |

## Generator — `planner/tests/test_generate.py`

| Test | Asserts |
|---|---|
| `test_construction_disabled_matches_task_08` | Toggle off, no override → identical output and RNG stream to the task-08 generator (byte-identical under a fixed seed). The "consume RNG only when construction is live" guarantee. |
| `test_construction_capped_at_construction_slots` | Toggle on, `construction_slots = 2`, a library that could compose more → **exactly ≤ 2** opt-in composed slots. |
| `test_construction_slots_zero_is_off` | Toggle on, `construction_slots = 0` → no opt-in construction. |
| `test_override_enables_construction_when_toggle_off` | `generate_plan(..., construction_slots=3)` with the profile toggle off → up to 3 composed slots. |
| `test_override_zero_disables_for_the_run` | Explicit `0` override → no opt-in construction even with the toggle on. |
| `test_balanced_fallback_still_uncapped` | Budget exhausted, a strict-`BALANCED` slot with no real dish → still composes (the fallback is not counted against the cap). |
| `test_one_pot_template_constructs_around_one_pot` | `dish_template = ONE_POT` + construction → composed slots are single one-pot recipes. |
| `test_mix_template_alternates_construction` | `MIX` + construction → composed slots alternate balanced-lean / one-pot-lean. |
| `test_construction_degrades_honestly` | Construction enabled, no recipes for a needed role → slot unfilled **with a reason**, never silently skipped. |
| `test_construction_deterministic_under_seed` | Same seed + same construction settings → byte-identical entries (recipe ids included). |
| `test_composed_slot_never_repeats_trio` | `forbidden_signatures` still prevents two identical compositions in one plan. |
| `test_locked_composed_slot_survives_regeneration` | Regeneration keeps a locked composed slot's `composed_recipe_ids` and `note`, and it consumes one construction-budget unit on the pass. |

## Persistence — `planner/tests/test_persist.py`

| Test | Asserts |
|---|---|
| `test_save_plan_creates_no_dish_for_composed_slot` | **The headline change.** Saving a plan with composed slots creates **zero** `Dish` rows; the entries carry `composed_recipe_ids`. |
| `test_save_plan_composed_name_stored` | `composed_name` persisted from the transient dish's name. |
| `test_two_identical_compositions_store_same_ids` | Both entries store the same id list; still zero `Dish` rows. |
| `test_update_plan_in_place_rewrites_unlocked_composed` | An unlocked composed entry's ids are replaced; a locked one is untouched. |
| `test_reroll_to_composed_stores_ids` | A re-roll returning a composition writes `composed_recipe_ids`. |
| `test_reroll_from_composed_clears_ids` | A re-roll from a composed slot to a real dish clears `composed_recipe_ids` / `composed_name`. |
| `test_swap_to_real_dish_clears_composed_and_lock` | Manual swap sets `dish`, clears `composed_recipe_ids`, clears `is_locked` (D50). |
| `test_failed_save_leaves_no_plan` | Unchanged guarantee — a mid-write failure leaves no `MealPlan` and no dishes. |
| `test_materialise_helper_removed` | `persist` no longer exposes `_materialise_composed_dish` (guards against a silent revert). |

## Save-as-dish — `planner/tests/test_materialise.py`

| Test | Asserts |
|---|---|
| `test_save_composed_entry_creates_dish` | `Dish(owner=user, visibility=PRIVATE)` + ordered `DishComponent`s (`servings == 1`) from the stored ids. |
| `test_save_composed_entry_points_entry_and_clears` | `entry.dish` now set; `composed_recipe_ids` / `composed_name` cleared. |
| `test_save_composed_entry_attaches_tags` | Supplied tag ids land on the new dish; an invisible / non-existent tag id is rejected. |
| `test_save_composed_entry_idempotent` | Second call on an entry that already has a dish → `PlannerError` / `409`. |
| `test_save_composed_entry_refuses_now_invisible_recipe` | A stored recipe id no longer `visible_to(user)` → refused, nothing created. |
| `test_save_composed_entry_owner_only` | A sharee of the plan and an unrelated user are both refused. |

## Shopping list — `planner/tests/test_shopping.py`

| Test | Asserts |
|---|---|
| `test_composed_entry_contributes_ingredients` | A composed slot's recipes' ingredients appear on the generated list, correctly scaled/aggregated. |
| `test_plan_of_only_composed_entries_produces_list` | No real dishes anywhere → still a correct shopping list. |
| `test_composed_meal_lines_have_no_dish_provenance` | Lines from a composed meal carry `ListItem.dish is None`; `generated_from` is the plan (D43 amend, accepted). |
| `test_no_flatten_logic_added_to_planner` *(structural)* | `planner/services/shopping.py` still imports its flatten/aggregate from `lists.services` — no local reimplementation. |

## Security — `planner/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_generator_never_composes_from_invisible_recipe` | Construction only ever draws from `Recipe.objects.visible_to(user)`. |
| `test_share_refused_when_composed_recipe_not_grantable` | Sharing a plan whose composed slot uses a recipe the plan owner does not own and the recipient cannot see → refused, **names the recipe**. |
| `test_share_cascades_read_to_composed_recipes` | A successful plan-share grants the recipient read on the composed recipes and their sub-recipe / ingredient graphs. |
| `test_save_as_dish_idor` | Sharee → `403`, stranger → `403`, on `POST …/save-as-dish/`. |
| `test_entry_api_tombstones_invisible_component_name` | `component_recipes` returns the raw id but `name: null` for a recipe the viewer cannot see (D48 parity). |
| `test_construction_time_bounded` | Construction enabled against a hostile profile (many zero tag-limits colliding with tagged role recipes) stays within `MAX_BACKTRACKS` and a wall-clock bound. |

## API — `planner/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_profile_api_round_trips_construction_gear` | `POST` / `PATCH` / `GET` carry both new fields; `construction_slots = 8` → `400`. |
| `test_generate_accepts_construction_slots_override` | The override changes the previewed plan's composed-slot count. |
| `test_regenerate_accepts_construction_slots_override` | Same on the regenerate action. |
| `test_save_as_dish_action_creates_dish` | `201`, dish owned by the caller, entry updated. |
| `test_save_as_dish_conflict` | `409` when the entry already has a dish. |
| `test_save_as_dish_method_not_allowed` | `GET` / `PUT` / `DELETE` on the action → `405`. |
| `test_entry_serializer_exposes_composed_state` | `composed_recipe_ids`, `composed_name`, `is_composed`, `component_recipes` present and correct for a **saved** composed slot (the old `is_auto_composed: false` bug is fixed). |
| `test_patch_dish_clears_composed_fields` | `PATCH`ing `dish` onto a composed entry clears `composed_recipe_ids`. |

## Views — `planner/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_profile_form_renders_and_saves_construction_gear` | The checkbox + number render, and a submit persists them. |
| `test_generate_screen_renders_construction_override` | The "new dishes this week" field is present and a non-empty value takes effect. |
| `test_plan_grid_renders_composed_slot` | A composed slot shows `composed_name`, its linked component recipes, and a "Save as dish" control. |
| `test_save_as_dish_modal_flow` | `GET` renders the form into `#modal` (does not extend `base.html`); `POST` swaps the slot card and clears `#modal` OOB; the HTMX target is the card, not the button (D39). |
| `test_save_as_dish_works_without_js` | The standalone `save-as-dish` page renders full-page and its `POST` redirects back to the plan with the slot now a real dish. |
| `test_old_auto_composed_label_gone` | No template compares `notes == "Auto-composed by the meal planner."` any more. |

## Manual verification

1. Enable construction on a profile (`allow_dish_construction`, `construction_slots = 3`),
   generate a week; confirm ~up to 3 slots are "composed" meals built from recipes, the rest
   real dishes, and the grid marks them.
2. Click "Save as dish" on a composed slot; fill in description + tags; confirm a real `Dish`
   appears in *Dishes*, the slot now links to it, and re-opening the plan shows no "Save as
   dish" button there.
3. Lock a composed slot, regenerate; confirm it survives unchanged and the other slots reroll.
4. Disable JavaScript; repeat step 2 via the standalone page.
5. Share the plan with a second user whose account cannot see one of the composed recipes;
   confirm the share is refused and names the recipe. Grant access, share again; confirm the
   second user can open the composed meal's recipes.
6. Generate with construction on, save the plan, generate a shopping list; confirm the
   composed meals' ingredients are on it.

## Definition of Done

- [ ] Every test above exists and passes; full suite green; `ruff` clean; no pending migrations.
- [ ] **Generating or saving a plan creates zero `Dish` rows** — composed dinners live only on
      `MealPlanEntry.composed_recipe_ids` until "Save as dish".
- [ ] Byte-identical generator output under a fixed seed, construction **off and on**.
- [ ] Construction is capped by `construction_slots`; the strict-`BALANCED` fallback is
      unchanged and uncapped.
- [ ] Every composition query goes through `.visible_to(user)`; composed component names are
      tombstoned for viewers who cannot see the recipe.
- [ ] Sharing a plan cascades read to composed recipes' graphs, and is refused (naming the
      recipe) when it cannot.
- [ ] `save-as-dish` is owner-only, idempotent, and refuses a now-invisible recipe.
- [ ] The whole flow works with JavaScript disabled.
- [ ] `ARCHITECTURE.md`: 10th gear recorded; D49 / D50 / D43 / D47 / D48 amended.
- [ ] The `is_auto_composed`-by-`notes`-string BACKLOG item struck as retired.
- [ ] All manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
