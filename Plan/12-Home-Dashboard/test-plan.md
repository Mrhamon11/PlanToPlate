# 12 — Home Dashboard · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Recently viewed — `core/tests/test_recent.py`

| Test | Asserts |
|---|---|
| `test_record_view_creates_one_row` | |
| `test_viewing_twice_updates_not_appends` | One row, later `viewed_at`. The append-only failure mode this model exists to avoid. |
| `test_recent_ordered_newest_first` | |
| `test_recent_capped_at_limit` | Viewing 60 objects leaves 50 rows; the oldest went. |
| `test_record_view_swallows_write_failure` | A raising `update_or_create` does not propagate — the detail page still renders. |
| `test_recent_excludes_now_invisible_object` | **The security case.** Record a view of a shared recipe, revoke the share, and it is gone from `recent_for` — not rendered from the stored row. |
| `test_recent_excludes_deleted_object` | A stale row is skipped, not a 500. |
| `test_recent_is_per_user` | Bob's history never appears in Alice's. |

## View recording — `core/tests/test_recent_views.py`

| Test | Asserts |
|---|---|
| `test_recipe_detail_records_view` | |
| `test_dish_detail_records_view` | |
| `test_book_detail_records_view` | |
| `test_list_page_does_not_record` | Scrolling past a recipe is not viewing it. |
| `test_htmx_fragment_does_not_record` | A fragment refresh must not bump `viewed_at`. |
| `test_print_view_does_not_record` | |

## Dashboard service — `core/tests/test_dashboard.py`

| Test | Asserts |
|---|---|
| `test_this_week_shows_active_plan` | Today first and flagged. |
| `test_this_week_ignores_ended_plan` | A plan that ended yesterday yields the empty state, not the most recent plan. |
| `test_shopping_panel_uses_default_list` | Not some other list of the user's. |
| `test_shopping_panel_progress_counts` | checked / total. |
| `test_favourites_exclude_unshared_object` | A favourited-then-unshared recipe is gone. |
| `test_shared_with_you_lists_others_objects` | Own objects excluded. |
| `test_shared_with_you_hides_share_audience` | D35 — the owner's username only, never the rest of `shared_with`. |
| `test_suggestion_excludes_empty_dishes` | Matches the planner's rule (task 06 `design.md`). |
| `test_suggestion_only_from_visible_dishes` | |
| `test_section_counts_are_visibility_scoped` | Bob's recipe count is Bob's, not the table's. |
| `test_empty_panels_are_absent` | A brand-new user's context carries no empty panels to render. |
| `test_dashboard_query_count` | A user with data in **every** panel stays within a bounded query count. The most-requested page in the app. |

## UI — `core/tests/test_templates.py`

| Test | Asserts |
|---|---|
| `test_home_dashboard_cards` | *(existing — updated, not deleted)* The five section links are still present, now with counts, and no "Coming soon." remains. |
| `test_new_user_home_is_not_blank` | Section links plus a "get started" line; no empty panel boxes. |
| `test_panels_render_without_htmx` | The plain test client gets every panel's content in the first response — no `hx-trigger="load"`, per the task 02 no-JS rule. |
| `test_panel_fragment_endpoint_returns_partial` | And does not extend `base.html`. |
| `test_reroll_suggestion_swaps_panel` | HTMX re-roll targets the panel, not the triggering element. *(Task 06's item-10 bug, which was exactly this omission.)* |

## API — `core/tests/test_dashboard_api.py`

| Test | Asserts |
|---|---|
| `test_dashboard_endpoint_requires_auth` | |
| `test_dashboard_endpoint_matches_service` | Same panel content as the HTML page — one implementation, two renderings. |
| `test_dashboard_endpoint_is_read_only` | `POST` / `PUT` / `DELETE` → 405. |
| `test_dashboard_never_exposes_another_users_history` | |

## Manual verification

1. Log in as a user with a plan, a shopping list, favourites and history; confirm every panel
   shows the right thing and each link lands where it says.
2. Log in as a brand-new user; confirm the page reads as deliberate rather than broken.
3. Disable JavaScript and reload; confirm every panel is still fully rendered.
4. Have a second user share a recipe, view it, then revoke the share; confirm it disappears
   from recently-viewed and favourites on the next load.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] `ruff` clean; suite green; no pending migrations.
- [ ] Every panel query goes through `.visible_to(user)` — no hand-rolled ownership filters.
- [ ] Recently-viewed re-filters at render time; a revoked object cannot be rendered from a
      stored row.
- [ ] `RecentView` rows are never readable by any user but their own.
- [ ] The dashboard has a bounded query count.
- [ ] The whole page works with JavaScript disabled.
- [ ] `N4.14` struck through in `Plan/N4-PWA-And-Polish/tasks.md` as delivered here.
- [ ] The 12.9 share-ordering decision recorded in `ARCHITECTURE.md`.
- [ ] All four manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
