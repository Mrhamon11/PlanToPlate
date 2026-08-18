# 08 — Meal Planner · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

**Every generator test pins a seed.** A test that depends on unseeded randomness is a test that
will fail one morning for no reason and be deleted, and then the planner is untested.

## Models — `planner/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_profile_days_range` | 0 and 8 rejected. |
| `test_profile_slots_not_empty` | |
| `test_min_rating_range` | |
| `test_one_default_profile_per_user` | |
| `test_entry_unique_per_day_slot` | |
| `test_plan_stores_seed_and_snapshot` | |
| `test_entry_dish_set_null_on_delete` | The slot empties and stays re-rollable. |

## Candidate pool — `planner/tests/test_candidates.py`

One test per gear, each proving the gear actually narrows the pool.

| Test | Asserts |
|---|---|
| `test_pool_only_visible_dishes` | Another user's private dish is **never** a candidate. **A planner that suggests a dish you cannot see is a data leak wearing a friendly hat.** |
| `test_pool_respects_source_scope_mine` | Excludes shared and public. |
| `test_pool_respects_source_scope_shared` | |
| `test_pool_excludes_empty_dishes` | A dish with no components is not a meal. |
| `test_pool_excludes_excluded_tag` | |
| `test_pool_excludes_excluded_ingredient` | |
| `test_exclusion_catches_subrecipe_ingredient` | An allergen buried in a sub-recipe is caught. An exclusion that only checks top-level ingredients is not an allergy filter. |
| `test_pool_respects_min_rating` | |
| `test_min_rating_uses_requesters_stats` | Bob's pool reflects Bob's ratings, not Alice's. |
| `test_pool_respects_favorites_only` | |
| `test_pool_respects_max_total_minutes` | |
| `test_pool_respects_no_repeat_days` | Something cooked 3 days ago is excluded at `no_repeat_days=14`. |
| `test_no_repeat_uses_requesters_last_made` | |
| `test_pool_query_count` | Bounded — building the pool must not N+1 across every dish's flattened ingredients. |

## Generator — `planner/tests/test_generate.py`

| Test | Asserts |
|---|---|
| `test_same_seed_produces_identical_plan` | Byte-identical entries. **Without this the planner cannot be tested at all.** |
| `test_different_seed_produces_different_plan` | Given a pool large enough to make a collision unlikely. |
| `test_generates_requested_number_of_days` | |
| `test_generates_all_requested_slots` | |
| `test_respects_tag_limit` | `{"chicken": 1}` over 7 days yields exactly one chicken dish. The headline requirement. |
| `test_tag_limit_zero_excludes_entirely` | |
| `test_locked_entries_preserved_on_regenerate` | |
| `test_locked_entries_consume_tag_budget` | A locked chicken dish plus a limit of 1 means no *second* chicken. Easy to get wrong, and wrong in the direction the user will notice. |
| `test_balanced_template_covers_roles` | Selected dishes span protein, carb, and vegetable. |
| `test_one_pot_template_selects_one_pot` | |
| `test_mix_template_varies` | |
| `test_favorites_bias_increases_selection_rate` | Over many seeds, favourites are selected more often than the unweighted rate. |
| `test_no_duplicate_dishes_within_plan` | Unless the pool is too small to avoid it. |
| `test_partial_plan_when_pool_too_small` | Unfilled slots, and the plan still returns. |
| `test_unfilled_slots_have_reasons` | Every unfilled slot carries a human-readable cause. |
| `test_empty_pool_returns_all_unfilled_with_reason` | The new-user path. |
| `test_never_hangs_on_impossible_constraints` | Completes within a strict time bound. **The infinite-loop guard.** |
| `test_backtracking_bounded` | Backtracks are capped. |
| `test_generation_does_not_persist` | Preview writes nothing to the database. |

## Composition — `planner/tests/test_compose.py`

| Test | Asserts |
|---|---|
| `test_composes_protein_carb_vegetable` | |
| `test_composed_dish_not_persisted_on_preview` | Regenerating five times leaves zero new `Dish` rows. Otherwise experimentation litters the database. |
| `test_composed_dish_persisted_on_save` | |
| `test_composition_respects_exclusions` | |
| `test_composition_respects_visibility` | |
| `test_composition_falls_back_when_role_missing` | No vegetable recipes → unfilled with a reason, not a crash. |
| `test_composed_dish_name_lists_components` | |

## Persistence — `planner/tests/test_persist.py`

| Test | Asserts |
|---|---|
| `test_save_plan_creates_entries` | |
| `test_save_is_atomic` | A failure leaves no plan and no composed dishes. |
| `test_profile_snapshot_recorded` | Editing the profile afterward does not change the snapshot. |
| `test_deleting_profile_keeps_plan` | `SET_NULL`; the snapshot preserves the explanation. |

## Shopping list — `planner/tests/test_shopping.py`

| Test | Asserts |
|---|---|
| `test_generates_shopping_list` | Ingredients from every planned dish appear. |
| `test_creates_default_list_when_none_exists` | Named "Shopping List" — the stated requirement. |
| `test_uses_existing_default_list` | |
| `test_regeneration_does_not_duplicate` | The C8 guarantee, proven end to end through the planner. |
| `test_manual_items_preserved` | |
| `test_staples_excluded_by_default` | |
| `test_preview_writes_nothing` | |
| `test_aggregates_across_week` | Onion needed by three dishes appears once with the summed total. |
| `test_subrecipe_quantities_correct_through_planner` | The full 05 → 06 → 07 → 08 chain, verified against a hand-computed total. **The integration test that proves the whole feature.** |

## API — `planner/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_generate_returns_preview` | Unsaved. |
| `test_generate_accepts_seed` | |
| `test_invalid_seed_rejected` | |
| `test_persist_plan` | |
| `test_regenerate_respects_locks` | |
| `test_reroll_single_entry` | Other entries unchanged. |
| `test_manual_swap_entry` | |
| `test_profile_crud` | |

## Security — `planner/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_plan_idor_matrix` | |
| `test_profile_is_private_to_owner` | |
| `test_cannot_generate_from_others_profile` | |
| `test_cannot_swap_in_invisible_dish` | Manual entry assignment is visibility-checked. |
| `test_cannot_inject_profile_snapshot` | Server-generated only. |
| `test_generation_time_bounded` | A hostile profile cannot pin the CPU. |

## UI — `planner/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_profile_form_renders_all_gears` | All eight present. |
| `test_plan_grid_renders` | |
| `test_unfilled_slot_shows_reason_inline` | |
| `test_lock_toggle_htmx` | |
| `test_reroll_htmx_updates_one_card` | |
| `test_empty_pool_shows_guidance` | A new user gets a route forward, not a blank grid. |
| `test_mobile_layout_stacks` | |

## Manual verification

1. Seed a realistic library (~15 dishes), set chicken ≤ 1, generate 7 days, and confirm by eye
   that exactly one chicken meal appears.
2. Lock three days, regenerate, confirm those three are untouched and the tag limits still hold
   across the whole week.
3. Generate the shopping list; hand-check three ingredient totals against the recipes.
4. Regenerate the plan and confirm the shopping list does not double.
5. As a brand-new user with no dishes, press Generate and confirm the explanation is useful.
6. Run the whole flow on a phone.

## Definition of Done

- [ ] Every test above exists and passes; every generator test pins a seed.
- [ ] `ruff` clean; suite green; no pending migrations.
- [ ] Identical seed → identical plan, proven.
- [ ] The generator never hangs and always explains unfilled slots.
- [ ] The candidate pool is built exclusively from `visible_to`.
- [ ] Composed dishes are not persisted on preview.
- [ ] Shopping-list regeneration does not duplicate — proven through the planner.
- [ ] All six manual verifications performed and reported.
- [ ] The `MealPlan`-vs-`List` open question in `MILESTONES.md` §8 is resolved and recorded.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
