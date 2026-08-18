# 04 — Units & Ingredients · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Unit model — `catalog/tests/test_units.py`

| Test | Asserts |
|---|---|
| `test_seeded_units_exist` | The base unit of each dimension exists with `to_base_factor == 1`. |
| `test_unit_name_unique` | |
| `test_unit_str` | Renders the abbreviation. |

## Conversion — `catalog/tests/test_conversion.py`

The correctness core of this task.

| Test | Asserts |
|---|---|
| `test_convert_within_mass` | 1 kg → 1000 g; 1 lb → 453.592 g (3dp). |
| `test_convert_within_volume` | 1 cup → 236.588 ml; 1 tbsp → 3 tsp. |
| `test_convert_same_unit_is_identity` | Returns the input exactly, untouched by factor arithmetic. |
| `test_convert_round_trip` | g → oz → g returns the original within tolerance. |
| `test_mass_to_volume_with_density` | 100 g water → 100 ml. |
| `test_mass_to_volume_without_density_raises` | `IncompatibleUnits`. **Never guess** — a fabricated density yields a confidently wrong shopping list. |
| `test_count_to_mass_always_raises` | Even with a density set. |
| `test_convert_uses_decimal_not_float` | The return is `Decimal`, and a `0.1 + 0.2` style sum is exact. |
| `test_convert_precision_preserved` | ⅓ cup round-trips without accumulating drift. |
| `test_humanize_common_fractions` | 0.25 cup → "¼ cup"; 0.5 → "½"; 1.5 → "1½". |
| `test_humanize_plural` | 1 cup vs 2 cups. |
| `test_humanize_falls_back_to_decimal` | 0.37 cup does not become an absurd fraction. |
| `test_zero_quantity` | Converts to zero, no division error. |

## Ingredient model — `catalog/tests/test_ingredients.py`

| Test | Asserts |
|---|---|
| `test_ingredient_is_owned` | Subclasses `OwnedModel`; defaults to PRIVATE. |
| `test_name_unique_per_owner_case_insensitive` | "Chicken Breast" and "chicken breast" collide for one owner. |
| `test_same_name_allowed_across_owners` | Alice and Bob may each have "Flour". |
| `test_system_ingredient_names_unique` | |
| `test_negative_density_rejected` | Validator error. |
| `test_zero_density_rejected` | Would divide by zero in conversion. |
| `test_staple_defaults_false` | |
| `test_hooks_present` | `share_dependencies()` and `copy_children()` exist — the task 03 convention test. |

## Seeding — `catalog/tests/test_seed.py`

| Test | Asserts |
|---|---|
| `test_seed_creates_system_objects` | All seeded rows are `is_system=True` with `owner=None`. |
| `test_seed_is_idempotent` | Two runs → the same row count. |
| `test_seed_does_not_touch_user_ingredients` | A user ingredient sharing a seed name is left unmodified. |
| `test_seeded_densities_present` | Water, flour, sugar, and oil all have a density. |
| `test_seeded_staples_marked` | Salt, pepper, and oil are staples. |

## API — `catalog/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_list_units` | 200, filterable by dimension. |
| `test_units_readonly_for_regular_user` | POST → 403. |
| `test_units_writable_by_staff` | |
| `test_ingredient_list_respects_visibility` | Carol does not see Alice's private ingredient. |
| `test_ingredient_create_sets_owner` | From `request.user`, ignoring any posted `owner`. |
| `test_ingredient_search` | `?search=chick` matches "Chicken Breast", case-insensitively. |
| `test_ingredient_filter_by_tag` | |
| `test_ingredient_filter_mine` | Excludes system and shared rows. |
| `test_convert_endpoint_success` | |
| `test_convert_endpoint_incompatible_returns_400` | The body explains *why*, naming both units. |
| `test_delete_in_use_returns_409` | The response names the blocking recipes rather than a bare error. |
| `test_copy_system_ingredient` | Yields an editable, private, user-owned copy. |

## Security — `catalog/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_ingredient_idor_matrix` | The full task 03 matrix, applied to this concrete model. |
| `test_cannot_modify_system_ingredient` | Even as staff, through the API. |
| `test_cannot_share_others_ingredient` | |
| `test_search_does_not_leak_invisible_rows` | Searching an exact private name returns nothing. **Search is a classic visibility bypass** — the filter must compose with `visible_to`, not replace it. |
| `test_sql_wildcards_in_search_are_literal` | A `%` or `_` in the search term matches literally, not as a wildcard. |

## UI — `catalog/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_ingredient_list_requires_login` | |
| `test_list_shows_only_visible` | |
| `test_htmx_search_returns_fragment` | No `<html>` in the response. |
| `test_create_via_form` | |
| `test_quick_add_returns_row_fragment` | The task 05 contract. |
| `test_cannot_edit_others_ingredient_via_html` | 404, matching the API. |

## Manual verification

1. Run `seed_catalog`, browse the ingredient list, confirm ~150 built-ins appear as read-only.
2. Copy a system ingredient, edit the copy, confirm the original is untouched.
3. On a phone-width viewport, search and filter with touch only.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] `ruff` clean; suite green; no pending migrations.
- [ ] The conversion service never fabricates a density, and refuses with a clear reason.
- [ ] All quantities are `Decimal` end to end — a grep for `float(` in `catalog/` is empty.
- [ ] Seeding is idempotent and leaves user data alone.
- [ ] The task 03 convention tests still pass with `Ingredient` registered.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
