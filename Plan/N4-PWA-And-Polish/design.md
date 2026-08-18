# N4 — PWA & Polish · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)
>
> *Nice-to-have. Lighter detail. Best done last, once the screens have stopped moving.*

## Goal

Make the app installable, usable with a bad kitchen signal, and pleasant to use — the polish
pass that turns a working app into one people actually reach for.

**Depends on:** 02, 08. Best after the MVP is in daily use, because that is when the real
friction becomes visible.

## PWA

The requirement asked that a native app be quick to build on top of what exists. A PWA delivers
most of that benefit for a fraction of the work: an icon on the home screen, a standalone
window, and offline access — no app store, no second codebase.

**Manifest** — name, short name, icons (192/512 plus maskable), `display: standalone`,
`theme_color`, `background_color`, `start_url: /`, portrait orientation, and shortcuts to
Shopping List and Meal Planner (the two things people open in a hurry).

**Service worker** — deliberately conservative:

- **Precache** the app shell: CSS, JS, fonts, icons, offline page.
- **Network-first** for HTML, falling back to cache, falling back to an offline page.
- **Cache-first** for versioned static assets.
- **Never cache API mutations.** Stale write behaviour is far worse than no offline support.
- Versioned cache names with cleanup on activate.

**A service worker is the easiest way to ship a bug you cannot recover from** — a bad one can
serve stale code to a user indefinitely. So: a kill switch (an unregister path), a cache
version tied to the deploy, and no caching of anything under `/api/` that is not a GET.

## Offline

Scoped tightly to the one case that matters: **the shopping list in a shop with no signal.**

- Cache the user's default shopping list on each visit.
- Offline, it renders read-only-ish: check-offs are queued in IndexedDB and replayed on
  reconnect.
- Everything else offline shows a clear "you're offline" page rather than a broken screen.

Full offline editing is explicitly out of scope — it needs conflict resolution, and task 07
already decided shared lists are single-writer. Queued check-offs on your own list have no
conflict to resolve, which is exactly why that narrow case is safe to support.

## Polish pass

Driven by actual use of the MVP, but the expected list:

- **Keyboard shortcuts** on desktop: `/` search, `n` new, `g r` / `g l` / `g p` navigation.
- **Loading and empty states** everywhere — every list, every async action.
- **Optimistic UI** for check-offs and favourite toggles, with rollback on failure.
- **Transitions** — subtle, and respecting `prefers-reduced-motion`.
- **Error recovery** — retry buttons instead of dead ends.
- **Search across everything** — one box over recipes, dishes, books, and ingredients.
- **Recently viewed** on the dashboard.
- **Cook mode** on recipe detail: large text, screen-wake-lock, step-by-step. The single
  highest-value polish item in a *cooking* app, and worth doing even if nothing else here is.

## Accessibility audit

Task 02 built the foundations; this verifies them across every screen actually built.

- Keyboard-only pass over every flow.
- Screen reader pass over the primary flows.
- Contrast check in both themes.
- Focus management on HTMX swaps — **content replaced under a screen reader without moving or
  announcing focus is invisible to that user**, and it is the most likely a11y defect in an
  HTMX app.
- `aria-live` on dynamic updates.
- `prefers-reduced-motion` honoured.

## Performance pass

- Lighthouse on the main screens; fix what it flags.
- Query-count regression tests on the heaviest views (feed, recipe list, plan grid).
- Image `loading="lazy"` and explicit dimensions (N1).
- CSS and JS minified; long-lived cache headers on hashed assets.

## Edge cases

- iOS PWA limitations: no push, storage eviction. Document rather than fight.
- A service worker update while the app is open: show a "new version available, reload" prompt
  rather than swapping under the user.
- Offline queue conflicting with a server-side change: last-write-wins on the user's own list,
  documented.
- Storage quota exceeded: fail gracefully, drop the cache, keep working online.

## Security notes

- The service worker is same-origin only and must never cache authenticated HTML that could be
  served to a different user on a shared device. Cache per session or not at all.
- **Log out must clear all caches and IndexedDB.** Otherwise the next person to use the phone
  can read the previous user's shopping list offline.
- CSP (task 10) must allow the worker: `worker-src 'self'`.
- The offline queue holds only the user's own check-off actions — no credentials, no tokens.
