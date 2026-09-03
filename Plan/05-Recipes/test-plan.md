# 05 — Recipes · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Models — `recipes/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_recipe_is_owned` | Subclasses `OwnedModel`, defaults PRIVATE. |
| `test_yield_required` | A recipe with no yield cannot be saved. |
| `test_yield_zero_rejected` | Zero yield is a division by zero in flatten. |
| `test_negative_yield_rejected` | |
| `test_component_requires_exactly_one_target` | Both set → constraint error; neither set → constraint error. |
| `test_components_ordered_by_position` | |
| `test_delete_ingredient_in_use_protected` | `ProtectedError`. |
| `test_delete_subrecipe_in_use_protected` | |
| `test_role_defaults_to_other` | |
| `test_hooks_return_dependencies` | `share_dependencies()` includes both sub-recipes and ingredients. |
| `test_copy_reuses_actors_existing_copy_of_a_shared_private_ingredient` | Copying two recipes that share one private ingredient reuses the first copy — no `IntegrityError` on the `(owner, name)` constraint. *(Task 05 dev-test finding.)* |
| `test_recopying_a_recipe_reuses_the_first_copys_subtree` | Re-copying a recipe points at the first copy's sub-recipe / nested ingredient, not a duplicate. |
| `test_copy_reuses_an_existing_same_named_ingredient_from_a_different_origin` | A copied component whose ingredient collides by name with one the actor already owns points at the existing row. |

## Stats — `recipes/tests/test_stats.py`

| Test | Asserts |
|---|---|
| `test_stats_created_lazily` | No row exists until something is set. |
| `test_stats_unique_per_user_recipe` | |
| `test_two_users_independent_stats` | Alice rating 5 and Bob rating 2 coexist. **The per-user model's whole reason for existing.** |
| `test_mark_made_increments_and_stamps` | `times_made` +1, `last_made_at` updated. |
| `test_rating_out_of_range_rejected` | 0 and 6 both fail. |
| `test_stats_not_copied_with_recipe` | A copy starts clean. |
| `test_stats_deleted_with_user` | |

## Cycle guard — `recipes/tests/test_graph.py`

| Test | Asserts |
|---|---|
| `test_self_reference_rejected` | A recipe cannot contain itself. |
| `test_two_hop_cycle_rejected` | A → B → A. |
| `test_deep_cycle_rejected` | A → B → C → D → A. |
| `test_cycle_error_names_the_chain` | The message identifies the offending path, or it is unfixable by the user. |
| `test_valid_dag_allowed` | A diamond (A → B, A → C, B → D, C → D) is legal and not mistaken for a cycle. |
| `test_max_depth_enforced` | Six levels raises. |
| `test_depth_five_allowed` | The boundary is inclusive as documented. |
| `test_guard_enforced_on_serializer` | The API refuses. |
| `test_guard_enforced_on_form` | The HTML form refuses. |
| `test_guard_enforced_on_admin` | The admin refuses. **Three write paths, three tests** — a guard on one path is not a guard. |

## Flatten — `recipes/tests/test_flatten.py`

The correctness core. Expected values hand-computed in the test.

| Test | Asserts |
|---|---|
| `test_flatten_simple_recipe` | A flat recipe returns its own components unchanged. |
| `test_flatten_scales_by_factor` | factor=2 doubles every quantity. |
| `test_flatten_sub_recipe_scaled_by_yield` | Marinara yields 4 cups; a parent using 1 cup contributes **a quarter** of marinara's ingredients. The single most important assertion in this task. |
| `test_flatten_sub_recipe_unit_converted` | A parent asking for 240 ml of a recipe yielding in cups converts before scaling. |
| `test_flatten_nested_two_levels` | Factors compound correctly. |
| `test_flatten_respects_depth_limit` | |
| `test_flatten_terminates_on_cycle` | Raises rather than hanging. |
| `test_flatten_records_provenance` | `from_recipes` names the contributing recipes. |
| `test_aggregate_sums_same_ingredient_same_dimension` | 200 g + 1 lb flour → one line. |
| `test_aggregate_keeps_incompatible_dimensions_separate` | 200 g + 2 cups flour with no density → **two** lines, not one invented number. |
| `test_aggregate_uses_density_when_available` | The same case, with a density → one line. |
| `test_aggregate_converts_to_friendly_unit` | 1500 g → "1.5 kg", not "1500 g". |
| `test_exclude_staples` | Salt and oil dropped when requested, present when not. |
| `test_flatten_returns_decimals` | Never `float`. |
| `test_flatten_query_count` | A 3-level, 20-component recipe flattens in a bounded number of queries. Guards against the N+1 that would make the meal planner unusable. |

## Scaling — `recipes/tests/test_scale.py`

| Test | Asserts |
|---|---|
| `test_scale_multiplies_quantities` | |
| `test_scale_does_not_persist` | The database is unchanged afterward. |
| `test_scale_fractional_factor` | 0.5 halves cleanly. |

## API — `recipes/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_create_recipe_with_components` | One nested request creates recipe and components. |
| `test_nested_write_is_atomic` | An invalid third component leaves **no** recipe behind. |
| `test_update_replaces_component_set` | |
| `test_flattened_endpoint` | |
| `test_scaled_endpoint` | |
| `test_made_endpoint_increments` | |
| `test_filters` | `role`, `tags`, `max_minutes`, `min_rating`, `favorite` each narrow correctly. |
| `test_filter_by_rating_uses_requesters_stats` | Bob's `min_rating` filter reads Bob's ratings, not Alice's. |
| `test_delete_subrecipe_in_use_returns_409` | Names the parents. |
| `test_copy_deep_copies_subrecipes` | The copy's tree is independent. |
| `test_subrecipe_component_with_incompatible_unit_rejected_at_validation` | A sub-recipe component whose unit is a different dimension from the sub-recipe's `yield_unit` is refused at `POST` with a clear message naming both units, not accepted and only failing later from `flattened`. *(Added in the task 05 review rework — this edge was not in the original plan.)* |

## Security — `recipes/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_recipe_idor_matrix` | The full task 03 matrix on this model. |
| `test_cannot_reference_invisible_ingredient` | Posting a component with a private ingredient ID belonging to someone else is **rejected**. Otherwise a user reads other people's ingredient data back through their own recipe. **Highest-value test in the task.** |
| `test_cannot_reference_invisible_subrecipe` | Same, for sub-recipes — and more serious, since a sub-recipe carries a full ingredient list. |
| `test_typeahead_only_returns_visible` | Ingredient and sub-recipe pickers never surface an invisible object's name. |
| `test_subrecipe_typeahead_excludes_cycles` | Candidates that would create a cycle are absent from the list, not merely rejected on submit. |
| `test_shared_recipe_hides_invisible_component` | Defence in depth: if a component is somehow invisible, the serializer degrades gracefully rather than 500ing or leaking. |
| `test_instructions_are_escaped` | `<script>` in instructions renders escaped. |
| `test_stats_are_private` | Alice cannot read or write Bob's stats through any endpoint. |

## UI — `recipes/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_list_shows_only_visible` | |
| `test_detail_404_for_invisible` | |
| `test_form_creates_recipe_with_components` | |
| `test_htmx_add_component_row` | Returns a fragment. |
| `test_htmx_scale_rerenders_quantities` | Nothing is persisted. |
| `test_subrecipe_expander_returns_fragment` | |
| `test_print_view_renders` | |
| `test_print_view_inlines_subrecipe_ingredients` | A sub-recipe on the print page lists its own ingredients (nested list rendered), not just its name. *(Task 05 dev-test finding.)* |
| `test_delete_via_confirm_removes_recipe` | Owner POST to `recipe-delete` deletes and redirects to the list. |
| `test_delete_refused_when_recipe_is_used_as_a_subrecipe` | `PROTECT` → message naming the parent, recipe untouched, no 500. |
| `test_delete_denied_for_read_only_holder` | A shared (non-owned) recipe: non-owner POST to `recipe-delete` 403s and deletes nothing. |
| `test_update_via_html_denied_for_read_only_holder` | A shared (non-owned) recipe is read-only through the HTML form — a non-owner POST to `recipe-update` 403s and writes nothing. Proves `Recipe` is wired to `OwnedObjectMixin`'s write-side defence. *(Added in the task 05 review — Recipe-specific regression test was missing.)* |
| `test_share_via_html_denied_for_read_only_holder` | A read-only holder POSTing to `recipe-share` 403s and grants no access — sharing is a right of ownership. *(Added in the task 05 review.)* |

## Manual verification

1. Build "Marinara" (yields 4 cups) and "Chicken Parm" (uses 1 cup marinara). Flatten Chicken
   Parm and confirm by hand that marinara's ingredients appear at exactly one quarter.
2. Try to make Marinara contain Chicken Parm — confirm it is not offered in the picker.
3. Create a recipe with four ingredients and one sub-recipe entirely on a 375px viewport.
4. Print preview a recipe.

## Definition of Done

- [x] Every test above exists and passes. (`test_guard_enforced_on_admin` is deferred to 09.4 —
      `recipes/admin.py` registers nothing yet — noted in `tasks.md` 05.12 and the 05 review.)
- [x] `ruff` clean; suite green; no pending migrations.
- [x] Cycle guard proven enforced on the serializer and the HTML form write paths
      (`test_guard_enforced_on_serializer`, `test_guard_enforced_on_form`); admin path → 09.4.
- [x] Sub-recipe yield scaling verified by the hand-computed test *and* manual check #1.
- [x] Aggregation never invents a density.
- [x] No `float` anywhere in `recipes/` — grep is empty (only the string "float" in prose /
      guard messages / test names remains).
- [x] The flatten query-count test passes.
- [x] All four manual verifications performed and reported (in the 05.12/05.14 rework report).
- [x] Subtasks ticked; `../MILESTONES.md` updated.
