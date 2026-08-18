# 07 — Lists & Shopping · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Models — `lists/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_list_is_owned` | |
| `test_item_requires_some_content` | Empty item rejected by the constraint. |
| `test_item_accepts_text_only` | |
| `test_item_accepts_ingredient_with_quantity` | |
| `test_item_quantity_without_unit_allowed` | "3 lemons". |
| `test_items_ordered_by_position` | |
| `test_deleting_recipe_nulls_item_fk` | The item **survives** as a tombstone. Losing a line off a list you are holding in a shop is worse than seeing a dead reference. |
| `test_one_default_shopping_list_per_user` | The filtered unique constraint fires on the second. |
| `test_two_users_can_each_have_a_default` | |

## Default list service — `lists/tests/test_default_list.py`

| Test | Asserts |
|---|---|
| `test_creates_when_missing` | Named "Shopping List", kind SHOPPING, flag set. |
| `test_returns_existing` | No second list created. |
| `test_race_safe` | Two concurrent calls yield one list, not two. |

## Population — `lists/tests/test_populate.py`

The heart of the task.

| Test | Asserts |
|---|---|
| `test_populate_adds_flattened_ingredients` | |
| `test_populate_aggregates_across_dishes` | Two dishes needing onion produce **one** line. |
| `test_populate_excludes_staples_by_default` | |
| `test_populate_includes_staples_when_asked` | |
| `test_regeneration_replaces_generated_items` | The list does not grow on a second run. **The C8 bug this whole design exists to prevent.** |
| `test_regeneration_preserves_manual_items` | A hand-added "batteries" survives. |
| `test_regeneration_scoped_to_source_plan` | Two plans feeding one list do not delete each other's items. |
| `test_regeneration_loses_checked_state_documented` | Asserts the accepted behaviour so a future change is a deliberate decision, not an accident. |
| `test_populate_is_atomic` | A failure mid-way leaves the list exactly as it was. |
| `test_populate_returns_summary` | Counts of added, replaced, and skipped. |
| `test_populate_sets_provenance` | Items record their contributing dish. |
| `test_populate_requires_visibility` | Expanding a dish the actor cannot see raises. |
| `test_populate_query_count` | A 7-dish plan stays within a bounded query count. |

## Item operations — `lists/tests/test_items.py`

| Test | Asserts |
|---|---|
| `test_check_and_uncheck` | |
| `test_clear_checked_removes_only_checked` | |
| `test_merge_duplicates_combines_same_ingredient` | Quantities summed, units converted. |
| `test_merge_duplicates_keeps_incompatible_separate` | Same rule as task 05's aggregation. |
| `test_merge_is_explicit_not_automatic` | Adding a duplicate does not silently merge. |
| `test_reorder_updates_positions` | |
| `test_add_dish_expands_to_ingredients` | |
| `test_add_recipe_adds_recipe_reference_not_ingredients` | Adding a *recipe* to a generic list adds the recipe as an item; adding a *dish to a shopping list* expands. The distinction is easy to get backwards. |

## API — `lists/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_crud_list` | |
| `test_add_item` · `test_update_item` · `test_delete_item` | |
| `test_default_shopping_endpoint_creates` | |
| `test_add_dish_endpoint` | |
| `test_clear_checked_endpoint` | |
| `test_filter_by_kind` | |
| `test_item_pagination_over_200` | |

## Security — `lists/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_list_idor_matrix` | |
| `test_cannot_add_invisible_recipe_to_list` | The read primitive again. |
| `test_cannot_add_invisible_dish_to_list` | |
| `test_cannot_add_invisible_ingredient_to_list` | |
| `test_cannot_populate_from_invisible_dish` | |
| `test_shared_list_is_read_only` | A user holding a shared list **cannot check items off**. Collaborative editing is out of scope, and this test pins that decision. |
| `test_cannot_modify_others_items_directly` | Hitting the item endpoint under someone else's list ID → 404. |
| `test_list_index_counts_do_not_leak` | Previews and counts never reveal invisible content. |

## UI — `lists/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_shopping_list_groups_by_aisle` | |
| `test_ungrouped_items_fall_back_to_alphabetical` | |
| `test_htmx_check_returns_fragment` | And the progress counter updates out-of-band. |
| `test_generated_items_visually_distinguished` | A distinguishing class or marker is present. |
| `test_provenance_shown_on_generated_items` | |
| `test_tombstoned_item_renders` | A null recipe FK renders "(deleted recipe)" rather than 500ing. |
| `test_regenerate_warns_when_items_checked` | |
| `test_tap_targets_on_shopping_items` | The checkbox row meets the 44px rule from task 02. |

## Manual verification

1. Add two dishes to a shopping list; confirm shared ingredients aggregate into single lines
   with correct totals.
2. Add "batteries" by hand, regenerate the plan, confirm batteries survives and nothing is
   duplicated.
3. On a phone, check off ten items one-handed. It should feel instant.
4. Delete a recipe referenced by a list item; confirm the item survives as a tombstone.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] `ruff` clean; suite green; no pending migrations.
- [ ] Regeneration is idempotent and never touches manual items — proven by test *and* manual
      check #2.
- [ ] Every content FK on an item is visibility-validated.
- [ ] A shared list is read-only for the recipient.
- [ ] All four manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
