# 12 — Home Dashboard · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

> **Start only after task 08 is COMPLETE.** The two panels that justify this task — this
> week's plan and the active shopping list — need tasks 07 and 08 to have landed. Everything
> before 12.5 could technically be built earlier; do not, or the dashboard gets designed
> around what happened to exist.

- [ ] **12.1 — `RecentView` model**
  Generic FK (`content_type` + `object_id`), `viewed_at`, `unique_together` on
  `(user, content_type, object_id)`, newest-first default ordering. Not an `OwnedModel` —
  private telemetry, no visibility of its own, so it declares nothing for task 03's hooks
  guard (see `core/README.md` on `contains_owned_children`).
  *Files:* `core/models.py`, migration
  *Done when:* viewing the same recipe twice leaves exactly one row.

- [ ] **12.2 — `core/services/recent.py`**
  `record_view(user, obj)` (`update_or_create`, then prune beyond `RECENT_VIEW_LIMIT = 50`)
  and `recent_for(user, limit)` returning live objects re-filtered through `.visible_to(user)`.
  `record_view` swallows and logs write failures — a locked database must not 500 a recipe page.
  *Files:* `core/services/recent.py`
  *Done when:* an object the user has lost access to no longer comes back from `recent_for`,
  and a raising `update_or_create` does not propagate.

- [ ] **12.3 — Wire recording into the detail views**
  A `RecordsRecentView` mixin applied to the recipe, dish and book detail views. Detail pages
  only — not lists, forms, print, or HTMX fragment endpoints, which would bump the timestamp
  on every re-render.
  *Files:* `core/mixins.py`, `recipes/views.py`, `meals/views.py`
  *Done when:* an HTMX fragment refresh of a detail page does not create or touch a row.

- [ ] **12.4 — `build_dashboard(user)`**
  One service returning a `DashboardContext` dataclass with an attribute per panel. All panel
  logic lives here; the view assembles nothing. Every panel query goes through `.visible_to`.
  *Files:* `core/services/dashboard.py`

- [ ] **12.5 — "This week" panel**
  The active `MealPlan` covering today — today first and marked, each slot naming its dish and
  linking to it. A plan that ended yesterday is not active; show the empty state instead.
  *Files:* `templates/core/_partials/_panel_this_week.html`

- [ ] **12.6 — "Shopping" panel**
  The default shopping list only (task 07's single-default constraint): checked/total progress
  and the first few unchecked items.
  *Files:* `templates/core/_partials/_panel_shopping.html`

- [ ] **12.7 — "Recently viewed" panel** *(absorbs `N4.14`)*
  The last ~8 recipes / dishes / books, newest first, each labelled with its kind. Resolves
  generic references with one query per content type, not one per row.
  *Files:* `templates/core/_partials/_panel_recent.html`

- [ ] **12.8 — "Favourites" panel**
  Favourited recipes and dishes from `RecipeStats` / `DishStats`, intersected with
  `visible_to` — a favourite can have been unshared since.
  *Files:* `templates/core/_partials/_panel_favourites.html`

- [ ] **12.9 — "Shared with you" panel**
  Objects owned by someone else that this user can currently see, with the owner's username.
  **Never** render the rest of the share audience (D35).
  *Files:* `templates/core/_partials/_panel_shared.html`
  *Note:* there is no share timestamp — `shared_with` is a plain M2M with no through model —
  so "recently" here means ordered by the object's `updated_at`. Adding a through model with
  `shared_at` would touch the task 03 keystone and every model that inherits it; decide
  deliberately, and record the choice in `ARCHITECTURE.md` either way.

- [ ] **12.10 — "What should I make?"**
  One randomly chosen visible dish, re-rollable through its fragment endpoint. Excludes dishes
  with no components, matching the planner's rule (task 06 `design.md`).
  *Files:* `templates/core/_partials/_panel_suggestion.html`

- [ ] **12.11 — Section links with counts**
  Replace the task-02 card grid in `_home_content.html`. The five section links stay
  unconditionally — they are the floor the page degrades to — but carry a live count each.
  *Files:* `templates/core/_partials/_home_content.html`, `static/css/components.css`
  *Done when:* `core/tests/test_templates.py::test_home_dashboard_cards` is updated rather
  than deleted; the five links must still be asserted.

- [ ] **12.12 — Empty states**
  Panels with nothing to say hide themselves; a brand-new user gets the section links, their
  (mostly zero) counts, and one "get started" line pointing at adding a first recipe. The page
  must never read as broken.
  *Files:* `templates/core/_partials/_home_content.html`

- [ ] **12.13 — Panel fragment endpoints**
  `/dashboard/panel/<name>/` per panel, for in-place refresh. **Enhancement only** — every
  panel is already rendered server-side on first load. No `hx-trigger="load"` anywhere: task
  02's no-JS parity rule means the dashboard must be complete without JavaScript.
  *Files:* `core/views.py`, `core/urls.py`

- [ ] **12.14 — Read-only dashboard API**
  `GET /api/dashboard/` serialising the same `DashboardContext`. The API and the HTMX UI share
  the service layer — no second implementation of any panel's rules.
  *Files:* `core/serializers.py`, `core/api.py`, `core/urls.py`

- [ ] **12.15 — Query budget and no-JS pass**
  A bounded query-count test against a user with data in every panel, and a JavaScript-disabled
  walkthrough of the finished page.
  *Files:* `core/tests/test_dashboard.py`

- [ ] **12.16 — Update the living document**
  Task 12 → AWAITING APPROVAL. Strike `N4.14` in `Plan/N4-PWA-And-Polish/tasks.md` as
  delivered here, and record the 12.9 share-ordering decision in `ARCHITECTURE.md`.
  *Files:* `Plan/MILESTONES.md`, `Plan/ARCHITECTURE.md`, `Plan/N4-PWA-And-Polish/tasks.md`
