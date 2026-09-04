# 12 — Home Dashboard · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Turn the home page from a menu into an answer.

Task 02 built `core:home` as a shell: five cards, one per section, captioned "Coming soon."
Tasks 04–08 each light their own card up on the way through (06 did recipes/dishes/books,
07.13a does lists, 08.14a does planner), so by the time this task starts the page is correct —
it is just **redundant**. Every one of those five links already sits in the top nav, two
centimetres above. A logged-in user lands on a page that tells them nothing they did not
already know.

This task replaces the card grid with a dashboard that answers the question someone actually
opens the app to ask: *what am I cooking, and what do I need to buy?*

**Depends on:** 07-Lists-And-Shopping and 08-Meal-Planner. Both are hard dependencies, not
soft ones — the two highest-value panels (this week's plan, the active shopping list) are
exactly the ones that need those models to exist. Building this task earlier would ship a
dashboard of leftovers and guarantee a second pass.

**Enables:** nothing. This is a leaf.

**Absorbs:** `N4.14 — Recently viewed`, which was a one-line stub pointing at
`core/views.py` and `templates/core/home.html`. It is the same feature, and N4 is the last
task in the project — recently-viewed is worth having long before the polish pass.

## The panels

Ordered by how often the answer is the one the user came for.

| Panel | Content | Empty state |
|---|---|---|
| **This week** | The active `MealPlan`'s next few days, today first and visually marked. Each slot names its dish and links to it. | "No plan yet" → link to generate one. |
| **Shopping** | The default shopping list: checked/total progress, and the first handful of unchecked items grouped as the list page groups them. | "Nothing on the list" → link to the list. |
| **Recently viewed** | The last ~8 recipes / dishes / books this user opened, newest first. | Hidden entirely — a brand-new user should not see an empty box. |
| **Favourites** | Favourited recipes and dishes from `RecipeStats` / `DishStats`. | Hidden entirely. |
| **Shared with you** | Objects owned by someone else that this user can currently see. | Hidden entirely. |
| **What should I make?** | One randomly chosen visible dish, re-rollable. | Hidden when the user can see no dishes. |
| **Sections** | The five section links, each with a count ("42 recipes"). | Always shown — this is the floor the dashboard degrades to. |

**Panels with nothing to say hide themselves.** A dashboard of six empty boxes is worse than
the card grid it replaced. The section links stay unconditionally so the page is never blank.

## Recently viewed — the only new persistence

```python
class RecentView(models.Model):
    user        → User, related_name="recent_views"
    content_type → ContentType
    object_id   = PositiveIntegerField()
    viewed_at   = DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "content_type", "object_id")]
        ordering = ["-viewed_at"]
```

Not an `OwnedModel` — it is private telemetry about a user, not an object a user owns, shares
or copies. It has no visibility of its own; see the security note below for how it is read.

**Persistent, not session-backed.** A session list needs no migration and is tempting, but this
is a phone-in-the-kitchen / laptop-on-the-sofa app for a household. History that does not
follow you between devices, and evaporates at logout, is not history. The migration is cheap.

**One row per user per object, updated in place.** `update_or_create` on
`(user, content_type, object_id)`, never an append-only event log. This matters more here than
it looks: recording a view is a **write on a page-read path**, and SQLite serialises writers.
An append-only table would put an unbounded, ever-growing write on the hottest GET in the app.
One row that gets its `viewed_at` bumped keeps the table at (users × objects they have opened)
and, with the cap below, far smaller than that.

**Capped per user.** After a write, prune anything beyond the most recent `RECENT_VIEW_LIMIT`
(50) rows for that user. Pruning on write rather than on read keeps the dashboard's read path
free of housekeeping.

**Failures are swallowed.** If recording a view raises — a locked database, most plausibly —
the detail page still renders. Nobody should get a 500 on a recipe because the app could not
write down that they looked at it. Log it and move on.

## Where recording happens

A `RecordsRecentView` mixin on the recipe, dish and book **detail** views only. Not list
pages (you did not view a recipe by scrolling past it), not forms, not print, not HTMX
fragment endpoints — a fragment refresh is not a fresh view and would bump the timestamp on
every re-render.

The mixin calls `core.services.recent.record_view(user, obj)`. Views do not touch the model
directly.

## Reading the dashboard

One service, `core.services.dashboard.build_dashboard(user) -> DashboardContext`, returning a
dataclass with one attribute per panel. The view assembles nothing; the template loops over
what it is given.

The REST API and the HTMX UI share the service layer, so this gets a read-only
`GET /api/dashboard/` returning the same structure serialised — a future native client's home
screen is the same query, and building the panel logic twice is exactly what the architecture
rule exists to prevent.

## Rendering, and the no-JS rule

Every panel renders **server-side on the first request**. No `hx-trigger="load"` lazy-loading:
task 02's parity rule says every screen works with JavaScript disabled, and a dashboard whose
content only arrives via HTMX is a blank page without it.

Each panel *also* gets its own fragment endpoint (`/dashboard/panel/<name>/`) so it can refresh
in place — re-rolling "what should I make?", ticking an item off the shopping preview — but
these are enhancements over already-rendered markup, not the delivery mechanism.

## Query budget

This is the most-requested page in the application: every login lands here, and it fans out
across six models. It gets a query-count test with a hard bound, exercised against a user who
has data in every panel. `select_related` / `prefetch_related` on every panel query; the
recently-viewed panel resolves its generic references with one query per content type, not one
per row.

## Edge cases

- **A brand-new user** sees the section cards, their counts (mostly zero), and nothing else.
  That page must still read as deliberate, not broken — it gets a short "get started" line
  pointing at "add your first recipe."
- **A stale recently-viewed row** — the object was deleted, or the user's access to it was
  revoked — is skipped silently at render and left in the table. See the security note.
- **A meal plan that ended yesterday** is not "this week." The panel shows the active plan
  covering today; if none does, it shows the empty state rather than the most recent plan.
- **Multiple shopping lists** — the panel shows the *default* one only, per task 07's
  single-default-per-user constraint. The others are one click away on the lists page.
- **"What should I make?" with one visible dish** returns that dish every time. Correct, if
  unsatisfying; not a bug to guard against.
- **A dish with no components** is excluded from "what should I make?" for the same reason the
  planner skips it (task 06 `design.md`).

## Security notes

- **Recently viewed is a read primitive and must be re-filtered on every render.** The row
  records that you *once* could see an object. Whether you can see it *now* is a separate
  question, and the answer can change — a share can be revoked, an object can go from `PUBLIC`
  back to `PRIVATE`. Every panel resolves its objects through `.visible_to(user)` at render
  time, and a row whose object no longer comes back is dropped from the response. Rendering a
  recently-viewed row's stored name or id without that re-check would leak the state of an
  object the user has since lost access to.
- **Never expose another user's `RecentView` rows** through any endpoint, including the API.
  What someone has been looking at is private, and there is no legitimate reader but themselves.
  The queryset is filtered by `user=request.user`, not by object ownership.
- **Favourites are per-user by construction** (`RecipeStats` / `DishStats`, D3) — the panel
  filters on `user=request.user` and then intersects with `visible_to`, because a favourited
  object can also have been unshared since.
- **"Shared with you" must not leak the share audience.** It lists objects, and per D35 the
  `shared_with` list is owner-only — the panel shows the object and its owner's username,
  never who else it was shared with.
