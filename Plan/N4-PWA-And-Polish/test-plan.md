# N4 — PWA & Polish · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Much of this task is browser behaviour that pytest cannot reach. The automated tests cover what
the server controls; the manual checklist covers the rest and is mandatory.

## Manifest and worker — `core/tests/test_pwa.py`

| Test | Asserts |
|---|---|
| `test_manifest_served` | Valid JSON, correct content type. |
| `test_manifest_has_required_fields` | name, icons, `start_url`, display. |
| `test_manifest_icons_exist` | Every referenced icon resolves, including maskable. |
| `test_manifest_linked_from_base` | |
| `test_service_worker_served_from_root_scope` | A worker served from `/static/` cannot control `/`. The classic PWA mistake. |
| `test_sw_never_caches_api_mutations` | Static analysis of `sw.js` — no POST/PATCH/DELETE caching. Stale writes are worse than no offline support. |
| `test_sw_cache_version_present` | Tied to the deploy so a new release invalidates. |
| `test_csp_allows_worker_src` | |

## Search — `core/tests/test_search.py`

| Test | Asserts |
|---|---|
| `test_search_spans_all_models` | |
| `test_search_respects_visibility` | Invisible objects never appear. The same bypass risk as task 04's search. |
| `test_search_empty_query` | |
| `test_search_query_count_bounded` | |

## Cook mode and polish — `recipes/tests/test_cook_mode.py`

| Test | Asserts |
|---|---|
| `test_cook_mode_renders` | |
| `test_cook_mode_requires_visibility` | |
| `test_steps_split_correctly` | |

## Performance regression — `core/tests/test_performance.py`

| Test | Asserts |
|---|---|
| `test_recipe_list_query_count` | |
| `test_feed_query_count` | |
| `test_plan_grid_query_count` | |
| `test_shopping_list_query_count` | Guards against a later change quietly reintroducing an N+1. |

## Accessibility — `core/tests/test_a11y_full.py`

| Test | Asserts |
|---|---|
| `test_all_pages_have_lang_and_title` | Parametrized over every route. |
| `test_all_images_have_alt` | |
| `test_all_form_inputs_labelled` | |
| `test_htmx_swaps_have_aria_live_or_focus_target` | Content replaced under a screen reader without focus management is invisible to that user — the most likely a11y defect in an HTMX app. |
| `test_reduced_motion_respected` | A `prefers-reduced-motion` block exists. |

## Manual verification — mandatory

**PWA**
1. Install to the home screen on Android and iOS; confirm the icon, name, and standalone window.
2. Confirm the shortcuts to Shopping List and Meal Planner work.
3. Deploy an update with the app open; confirm the reload prompt rather than a silent swap.
4. Deliberately break the worker, then recover using the kill switch **without** clearing
   browser data by hand.

**Offline**
5. Load the shopping list, enable airplane mode, check off five items, re-enable — confirm all
   five persisted.
6. Offline on any other page shows the offline page, not a broken screen.
7. **Log out, then log in as a different user on the same device. Confirm nothing of the first
   user's data is reachable, online or offline.**

**Polish and a11y**
8. Complete a full flow — create a recipe, build a dish, plan a week, generate a shopping list
   — using **keyboard only**.
9. Screen-reader pass over that same flow.
10. Cook mode on a phone propped in a kitchen: readable at arm's length, screen stays awake.
11. Lighthouse ≥ 90 on Performance, Accessibility, and Best Practices for the main screens.

## Definition of Done

- [ ] Every automated test above exists and passes.
- [ ] The app installs on Android and iOS.
- [ ] Offline check-offs queue and replay reliably.
- [ ] **Logout clears all caches and IndexedDB** — verified by manual check #7.
- [ ] The service worker has a working kill switch, verified by manual check #4.
- [ ] Full keyboard-only flow completed.
- [ ] Lighthouse ≥ 90 on the three named categories.
- [ ] All 11 manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated and **the project marked complete**.
