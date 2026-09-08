# 12 — Home Dashboard · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

> **Start only after task 08 is COMPLETE.** The two panels that justify this task — this
> week's plan and the active shopping list — need tasks 07 and 08 to have landed. Everything
> before 12.5 could technically be built earlier; do not, or the dashboard gets designed
> around what happened to exist.

- [x] **12.1 — `RecentView` model**
  Generic FK (`content_type` + `object_id`), `viewed_at`, `unique_together` on
  `(user, content_type, object_id)`, newest-first default ordering. Not an `OwnedModel` —
  private telemetry, no visibility of its own, so it declares nothing for task 03's hooks
  guard (see `core/README.md` on `contains_owned_children`).
  *Files:* `core/models.py`, migration
  *Done when:* viewing the same recipe twice leaves exactly one row.

- [x] **12.2 — `core/services/recent.py`**
  `record_view(user, obj)` (`update_or_create`, then prune beyond `RECENT_VIEW_LIMIT = 50`)
  and `recent_for(user, limit)` returning live objects re-filtered through `.visible_to(user)`.
  `record_view` swallows and logs write failures — a locked database must not 500 a recipe page.
  *Files:* `core/services/recent.py`
  *Done when:* an object the user has lost access to no longer comes back from `recent_for`,
  and a raising `update_or_create` does not propagate.

- [x] **12.3 — Wire recording into the detail views**
  A `RecordsRecentView` mixin applied to the recipe, dish and book detail views. Detail pages
  only — not lists, forms, print, or HTMX fragment endpoints, which would bump the timestamp
  on every re-render.
  *Files:* `core/mixins.py`, `recipes/views.py`, `meals/views.py`
  *Done when:* an HTMX fragment refresh of a detail page does not create or touch a row.

- [x] **12.4 — `build_dashboard(user)`**
  One service returning a `DashboardContext` dataclass with an attribute per panel. All panel
  logic lives here; the view assembles nothing. Every panel query goes through `.visible_to`.
  *Files:* `core/services/dashboard.py`
  *Landed (12.1–12.4 dev run, 2026-09-07):* `DashboardContext` carries `ObjectCard`
  (`kind` / `name` / `url` / `owner_username` — deliberately **no** `shared_with` handle so a
  template cannot violate D35), `ThisWeekPanel` / `PlannedDay` / `PlannedSlot`,
  `ShoppingPanel`, `SectionCount`, and `show_get_started: bool`. Empty panels are `None` /
  `[]`; `sections` is always the five links. New caps `FAVOURITES_LIMIT` /
  `SHARED_WITH_YOU_LIMIT` / `RECENT_LIMIT` = 8 (not in `design.md`; a panel is a glance and
  the 12.15 budget test needs them bounded). "This week" / "Shopping" narrow
  `.visible_to(user).filter(owner=user, …)` — a plan merely shared with you is not "my week".
  The 12.5–12.12 templates loop over this structure and add nothing.

- [x] **12.5 — "This week" panel**
  The active `MealPlan` covering today — today first and marked, each slot naming its dish and
  linking to it. A plan that ended yesterday is not active; show the empty state instead.
  *Files:* `templates/core/_partials/_panel_this_week.html`
  *Rework (task 12 reviewer, blocking #1):* the empty state is a **visible one-line CTA**, not
  a hidden panel. `_this_week` returns `core.services.dashboard.EmptyPanel(forward_url=…)`
  (`planner:plan-generate`) instead of `None` when there is no active plan; the partial
  branches on `.forward_url` and renders "No plan yet — generate one". `_home_content.html`
  includes this partial unconditionally.

- [x] **12.6 — "Shopping" panel**
  The default shopping list only (task 07's single-default constraint): checked/total progress
  and the first few unchecked items.
  *Files:* `templates/core/_partials/_panel_shopping.html`
  *Rework (task 12 reviewer, blocking #1):* same as 12.5 — `_shopping` returns
  `EmptyPanel(forward_url=reverse("lists:index"))` when there is no default shopping list, and
  the partial renders "Nothing on the list — start one". Included unconditionally.

- [x] **12.7 — "Recently viewed" panel** *(absorbs `N4.14`)*
  The last ~8 recipes / dishes / books, newest first, each labelled with its kind. Resolves
  generic references with one query per content type, not one per row.
  *Files:* `templates/core/_partials/_panel_recent.html`
  *Carried-forward review finding (12.1–12.4 review):* `core/tests/test_recent.py::test_viewing_twice_updates_not_appends`
  asserts `viewed_at >= first`, not `>`, so a "timestamp stops bumping" regression slips
  through if both writes land in one clock tick. Tighten with `time-machine`/`freezegun` when
  building the relative-timestamp display this panel needs.
  *Sub-note (12.5–12.16 dev run, 2026-09-07):* neither `time-machine` nor `freezegun` is a
  project dependency (`pyproject.toml`), and adding one needs sign-off — so the assertion is
  left as `>=` for now. This panel labels each row by kind only, no relative timestamp, so the
  display work that would have driven the tighter test did not materialise. Revisit if a
  "viewed 3h ago" caption is ever added, or fold `freezegun` in with the N4 polish pass.

- [x] **12.8 — "Favourites" panel**
  Favourited recipes and dishes from `RecipeStats` / `DishStats`, intersected with
  `visible_to` — a favourite can have been unshared since.
  *Files:* `templates/core/_partials/_panel_favourites.html`

- [x] **12.9 — "Shared with you" panel**
  Objects owned by someone else that this user can currently see, with the owner's username.
  **Never** render the rest of the share audience (D35).
  *Files:* `templates/core/_partials/_panel_shared.html`
  *Note:* there is no share timestamp — `shared_with` is a plain M2M with no through model —
  so "recently" here means ordered by the object's `updated_at`. Adding a through model with
  `shared_at` would touch the task 03 keystone and every model that inherits it; decide
  deliberately, and record the choice in `ARCHITECTURE.md` either way.

- [x] **12.10 — "What should I make?"**
  One randomly chosen visible dish, re-rollable through its fragment endpoint. Excludes dishes
  with no components, matching the planner's rule (task 06 `design.md`).
  *Files:* `templates/core/_partials/_panel_suggestion.html`

- [x] **12.11 — Section links with counts**
  Replace the task-02 card grid in `_home_content.html`. The five section links stay
  unconditionally — they are the floor the page degrades to — but carry a live count each.
  *Files:* `templates/core/_partials/_home_content.html`, `static/css/components.css`,
  `templates/core/_partials/_panel_sections.html`
  *Done when:* `core/tests/test_templates.py::test_home_dashboard_cards` is updated rather
  than deleted; the five links must still be asserted.
  *Landed:* section links moved into their own `_panel_sections.html` (rendered by
  `_home_content.html` unconditionally) so the same partial can back the `sections` fragment
  endpoint. Links carry `SectionCount.url` (a `reverse()`), which still resolves to the
  literal `/recipes/` … `/planner/` paths the test asserts.

- [x] **12.12 — Empty states**
  Panels with nothing to say hide themselves; a brand-new user gets the section links, their
  (mostly zero) counts, and one "get started" line pointing at adding a first recipe. The page
  must never read as broken.
  *Files:* `templates/core/_partials/_home_content.html`

- [x] **12.13 — Panel fragment endpoints**
  `/dashboard/panel/<name>/` per panel, for in-place refresh. **Enhancement only** — every
  panel is already rendered server-side on first load. No `hx-trigger="load"` anywhere: task
  02's no-JS parity rule means the dashboard must be complete without JavaScript.
  *Files:* `core/views.py`, `core/urls.py`
  *Landed:* `DashboardPanelView` (a plain `LoginRequiredMixin`/`View`) renders one panel
  partial from `build_dashboard`; names `this-week` / `shopping` / `recent` / `favourites` /
  `shared` / `public` / `suggestion` / `sections`, 404 on anything else. Only the suggestion
  panel wires an `hx-get` to it today (with `hx-target="#panel-suggestion"`, D39); its no-JS
  fallback is a plain GET of `core:home`. (`public` was added beyond the original 12.13 list —
  it is a real panel and should be refreshable; task 12 reviewer, 2026-09-07.)
  *Sub-note (task 12 reviewer, 2026-09-07 — N5):* of the eight mapped names only `suggestion`
  and `sections` are linked from any markup, and only `_panel_suggestion.html` has an empty
  branch. Hitting `/dashboard/panel/this-week/` (or `shopping` / `recent` / `favourites` /
  `shared` / `public`) as a user with no data for that panel returns a degenerate header-only
  `<section>` (empty `<a href="">`, empty `<ol>`). Not reachable through the UI today.
  Resolve alongside blocking finding #1: if "This week" / "Shopping" get visible empty states
  their partials become null-safe for free; for the rest, either give every partial an empty
  branch or drop the unused names from `_DASHBOARD_PANELS` until a panel needs in-place
  refresh. `test_panel_fragment_endpoint_returns_partial` currently exercises only `sections`
  + an unknown name.
  *Rework (task 12 reviewer, blocking #1):* `this-week` / `shopping` are now null-safe — their
  partials always have a payload (a real panel or an `EmptyPanel` CTA) and render their own
  empty branch, covered by `test_flagship_panel_fragments_are_null_safe_when_empty`. The
  remaining four unlinked names (`recent` / `favourites` / `shared` / `public`) still render a
  header-only shell for a user with no data for that panel — not reachable through the UI, and
  left as-is until a panel actually needs in-place refresh: at that point either give its
  partial an empty branch or drop the unused name from `_DASHBOARD_PANELS`.

- [x] **12.14 — Read-only dashboard API**
  `GET /api/dashboard/` serialising the same `DashboardContext`. The API and the HTMX UI share
  the service layer — no second implementation of any panel's rules.
  *Files:* `core/serializers.py`, `core/api.py`, `core/api_urls.py`, `config/urls.py`
  *Deviation:* `design.md`/this line said `core/urls.py`, but every app in the project splits
  its `/api/` routes into a separate `api_urls.py` mounted under `api/` by `config/urls.py`
  (`core/urls.py` is mounted at the site root). Followed that convention: new `core/api_urls.py`
  → `core_api:dashboard`. `DashboardAPIView` is a plain read-only `APIView` (no write verb),
  matching `accounts/api.py`.

- [x] **12.15 — Query budget and no-JS pass**
  A bounded query-count test against a user with data in every panel, and a JavaScript-disabled
  walkthrough of the finished page.
  *Files:* `core/tests/test_dashboard.py`
  *Carried-forward review finding (12.1–12.4 review):* `core/services/dashboard.py::_favourites`
  loads every favourited visible row before slicing to `FAVOURITES_LIMIT` in Python. Query
  *count* is unaffected but row volume is unbounded — push the limit into each queryset
  (`.order_by("name")[:FAVOURITES_LIMIT]`) while building this budget test.
  *Landed:* finding addressed — each `_favourites` queryset now slices `[:FAVOURITES_LIMIT]`
  in SQL. `test_dashboard_query_count` asserts `build_dashboard` for a user with data in every
  panel stays within a bounded query count. No-JS pass covered by
  `test_templates.py::test_panels_render_without_htmx` (every panel present, no
  `hx-trigger="load"`); the human walkthrough is part of handoff.
  *Rework (task 12 reviewer, N1):* bound tightened from 29 to **26** — the measured count for
  the every-panel dataset. The earlier "observed 23" predated this test building realistic
  ingredient/tag fixtures for the shopping panel; with them the aisle grouping adds the extra
  queries and 26 is the true floor. `_favourites` also now reserves half its slots per kind so
  8+ favourite recipes can no longer starve out favourite dishes (N2), pinned by
  `test_favourites_do_not_starve_dishes`.

- [x] **12.16 — Update the living document**
  Task 12 → COMPLETE (2026-09-08, owner-approved). `N4.14` struck in
  `Plan/N4-PWA-And-Polish/tasks.md`; the 12.9 share-ordering decision is D51 and the dashboard
  read-model contract is D52 in `ARCHITECTURE.md`; `MILESTONES.md` row rewritten.
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`, `Plan/N4-PWA-And-Polish/tasks.md`
