# 06 — Dishes & RecipeBooks · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Refactor safety — `recipes/tests/test_stats.py`

| Test | Asserts |
|---|---|
| *(existing task 05 stats suite)* | Passes **unchanged** after `RecipeStats` moves onto the abstract base. If a test needed editing, the refactor changed behaviour. |

## Dish models — `meals/tests/test_dish_models.py`

| Test | Asserts |
|---|---|
| `test_dish_is_owned` | |
| `test_servings_zero_rejected` | |
| `test_servings_negative_rejected` | |
| `test_components_ordered` | |
| `test_delete_recipe_in_use_protected` | |
| `test_total_minutes_parallel_prep` | Max prep + sum cook, not a naive total. |
| `test_total_minutes_empty_dish_is_zero` | Not an error. |
| `test_roles_returns_component_roles` | |
| `test_share_dependencies_returns_recipes` | |

## Dish flatten — `meals/tests/test_dish_flatten.py`

| Test | Asserts |
|---|---|
| `test_flatten_single_recipe_dish` | Matches the recipe's own flatten. |
| `test_flatten_combines_recipes` | Two recipes sharing an ingredient produce **one** aggregated line. |
| `test_flatten_scales_by_servings` | `servings=2` doubles that recipe's contribution only. |
| `test_flatten_with_subrecipes` | Task 05's yield scaling still applies through the dish. |
| `test_flatten_excludes_staples_when_asked` | |
| `test_flatten_empty_dish_returns_empty` | |
| `test_flatten_query_count` | A 4-recipe dish stays within a bounded query count. |

## RecipeBook models — `meals/tests/test_book_models.py`

| Test | Asserts |
|---|---|
| `test_book_is_owned` | |
| `test_recipe_unique_per_book` | Adding the same recipe twice fails. |
| `test_recipe_can_be_in_multiple_books` | An explicit requirement. |
| `test_entries_ordered_by_section_then_position` | |
| `test_deleting_recipe_removes_entry` | CASCADE — a deleted recipe leaves its books quietly. |
| `test_section_optional` | |

## API — `meals/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_create_dish_with_components` | |
| `test_dish_nested_write_atomic` | |
| `test_dish_flattened_endpoint` | |
| `test_dish_made_increments_stats` | |
| `test_add_recipe_to_book` | |
| `test_add_duplicate_recipe_returns_400` | |
| `test_remove_recipe_from_book` | |
| `test_reorder_book_entries` | |
| `test_book_ordering_by_name` | |
| `test_book_ordering_by_rating_uses_requester_stats` | Bob's ordering reflects Bob's ratings. |
| `test_delete_recipe_in_dish_returns_409` | Names the dishes. |
| `test_dish_filters` | |
| `test_dish_list_query_count` | A page of N dishes stays within a bounded query count — no per-row `visible_to`. Round-2 review finding: the list serializer was N+1 at the backend stage. |
| `test_book_list_query_count` | Same bound for a page of N books. |
| `test_create_dish_without_components` | Dev-test fix: an empty dish is allowed (`design.md` "Edge cases"); the API keeps the same contract as the HTML form. |

## Sharing and copying — `meals/tests/test_sharing.py`

| Test | Asserts |
|---|---|
| `test_sharing_dish_cascades_to_recipes` | And transitively to sub-recipes and ingredients. |
| `test_sharing_dish_with_foreign_recipe_refused` | The task 03 refusal, naming the blocker. |
| `test_copying_dish_deep_copies_recipes` | The copy's recipes are independent. |
| `test_copying_book_deep_copies_recipes` | |
| `test_copied_dish_has_no_stats` | |
| `test_editing_original_recipe_does_not_affect_copied_dish` | The independence guarantee end to end. |

## Security — `meals/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_dish_idor_matrix` | |
| `test_book_idor_matrix` | |
| `test_cannot_add_invisible_recipe_to_dish` | Rejected. |
| `test_cannot_add_invisible_recipe_to_book` | **The sneakiest read primitive in the app** — otherwise a guessed recipe ID becomes readable through your own book page. |
| `test_book_detail_does_not_expand_invisible_recipe` | Defence in depth if an entry somehow exists. |
| `test_recipe_typeahead_filtered` | |
| `test_dish_stats_private` | |

## UI — `meals/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_dish_list_visibility` | |
| `test_dish_detail_shows_combined_ingredients` | |
| `test_book_detail_groups_by_section` | |
| `test_add_to_book_from_recipe_page` | |
| `test_htmx_reorder_returns_fragment` | |
| `test_reorder_has_touch_buttons` | Up/down controls present, not drag-only — the task 02 touch-parity rule. |
| `test_large_book_copy_warns` | The confirmation names the recipe count. |
| `test_dish_form_creates_empty_dish` | Dev-test fix: zero component rows saves a dish with no components (`design.md` "Edge cases"). |
| `test_dish_form_update_can_remove_all_components` | Editing a dish down to zero components is allowed. |
| `test_dish_form_rejects_row_with_servings_but_no_recipe` | The empty-dish loosening still rejects a half-filled row. |
| `test_book_remove_control_opens_confirm_modal` | Dev-test fix: the `×` control is a styled `#modal` confirm (hx-get), never a raw `hx-confirm`. |
| `test_book_remove_confirm_modal_renders_for_htmx` | The confirm fragment renders for an htmx GET and names the recipe + book. |
| `test_book_remove_confirm_forbidden_for_non_owner` | A non-owner (book shared with them) gets 403; an invisible book 404s. |
| `test_book_remove_confirm_404_for_invisible_book` | |
| `test_book_remove_confirm_missing_entry_redirects` | Recipe already gone → redirect to the book, not a 500. |
| `test_book_remove_confirm_post_drops_entry_and_swaps_sections` | Posting the confirm removes the entry, returns the `#book-sections` fragment (card + emptied section gone) and an OOB `#modal` clear. |

## Manual verification

1. Build a dish of three recipes (a protein, a carb, a vegetable), confirm the combined
   ingredient list aggregates shared ingredients into single lines.
2. Put one recipe into three different books; confirm all three show it and deleting it from
   one leaves the others intact.
3. Reorder a book on a phone using only touch.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] The task 05 stats suite passes unchanged after the abstract-base refactor.
- [ ] `ruff` clean; suite green; no pending migrations.
- [ ] Visibility validated on every nested recipe reference in both models.
- [ ] Dish and book list endpoints have a bounded query count (round-2 N+1 finding closed).
- [ ] `DishComponentSerializer.recipe` field queryset scoped to `visible_to` (round-2 finding).
- [ ] Reordering works by touch without drag.
- [ ] All three manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
