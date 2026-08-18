# 02 — UI Shell · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

The template layer, the CSS system, and the HTMX conventions that every later screen builds on.
No domain features. This lands early precisely so that tasks 04–08 add screens instead of
inventing layout patterns seven separate times.

**Depends on:** 00-Foundations, 01-Users-And-Auth.
**Enables:** every task with a user interface.

## Template architecture

```
templates/
├── base.html                 # <head>, nav, messages, HTMX config, block content
├── _partials/
│   ├── _nav.html
│   ├── _messages.html        # hx-swap-oob target for flash messages
│   ├── _form_field.html      # one field, label, errors, help text
│   ├── _pagination.html
│   ├── _empty_state.html
│   └── _confirm_delete.html  # modal body, reused by every destructive action
└── <app>/
    ├── <model>_list.html
    ├── <model>_detail.html
    ├── <model>_form.html
    └── _partials/            # app-specific HTMX fragments
```

**Rules**

- A file starting with `_` returns an HTML *fragment* and never extends `base.html`.
- Every full page extends `base.html` and fills `{% block content %}`.
- An HTMX request (`request.htmx`, via a small middleware setting the flag from the
  `HX-Request` header) renders the fragment; the same view without the header renders the full
  page. **Every screen must work with JavaScript disabled** — HTMX enhances, it never enables.
  This is what keeps the app testable with Django's plain test client and keeps the back
  button working.

## CSS

Hand-written, mobile-first, in `static/css/`. No Tailwind, no Bootstrap — the app is small,
and a utility framework would bury the HTML the owner is trying to learn to read.

`app.css` opens with custom properties:

```css
:root {
  --space-1: .25rem; ... --space-6: 3rem;
  --color-bg; --color-surface; --color-text; --color-muted;
  --color-accent; --color-danger; --color-success;
  --radius; --shadow;
  --tap-target: 44px;
}
@media (prefers-color-scheme: dark) { :root { /* redefined tokens only */ } }
```

**Breakpoints:** base (mobile), `≥640px` (tablet), `≥1024px` (desktop). Mobile-first, so the
media queries only ever add.

**Layout:** CSS grid for page structure, flexbox within components. A single `.container`
(`max-width: 72rem`, centred, gutter padding) used by every page.

**Touch parity is a hard requirement.** Every interaction has a touch equivalent:
- Minimum 44×44px tap targets on anything clickable.
- No hover-only affordances — if it appears on hover, it also appears on focus, and on
  touch devices it is always visible.
- No drag-and-drop without an equivalent button path. Reordering (recipe components, list
  items) gets up/down buttons; drag is a desktop enhancement layered on top.
- Forms use appropriate `inputmode` and `type` so mobile keyboards do the right thing —
  `inputmode="decimal"` on quantities is a small thing that makes the app feel native.

## Navigation

Desktop: horizontal bar — Recipes · Dishes · Books · Lists · Planner · (Admin) · profile menu.
Mobile: bottom tab bar for the five primary destinations, overflow behind a menu.

A bottom bar on mobile beats a hamburger here: the primary destinations are few and fixed, and
the app is used one-handed in a kitchen.

Admin links render only for `is_staff`. Hiding them is presentation, not security — the actual
gate is on the view (task 09).

## HTMX conventions

Loaded from `static/js/htmx.min.js` — **vendored, not from a CDN.** The app runs on a home
server that may be reachable when the wider internet is not, and a CDN is a third party
watching every page load.

- `hx-boost` on the main nav for snappy page transitions with real URLs preserved.
- Inline edit: `hx-get` the form fragment into place, `hx-post` back, swap `outerHTML`.
- Delete: `hx-delete` with `hx-confirm` for low-stakes items; the `_confirm_delete.html` modal
  for anything that destroys user data.
- Flash messages arrive via `hx-swap-oob="true"` into `#messages`, so any fragment response
  can raise a message without owning the page.
- CSRF: `hx-headers='{"X-CSRFToken": "..."}'` set once on `<body>`.
- Loading state: `.htmx-indicator` spinner plus `hx-disabled-elt="this"` on submits, so a
  double tap on a slow phone connection cannot double-submit.

Alpine.js — vendored too — is used only for local UI state: dropdowns, modals, tab panels.
**No Alpine component may hold application data or talk to the server.** That is HTMX's job,
and mixing the two is how this kind of frontend rots.

## Base view helpers

`core/views.py`:

- `HtmxTemplateMixin` — picks `partial_template_name` when `request.htmx`, else
  `template_name`.
- `MessageMixin` — adds a flash message and, on HTMX responses, includes the OOB swap.
- `OwnedObjectMixin` — a placeholder here, filled in by task 03; declared now so later views
  do not invent their own.

## Accessibility

Semantic elements over `div` soup. Labels bound to inputs. Focus visible and never removed.
Landmark roles. Colour contrast at least 4.5:1 in both schemes. Errors announced via
`aria-live`. This is cheap when done at the shell and expensive when retrofitted.

## Edge cases

- A fragment request to a view that 302s (session expiry) — HTMX follows the redirect and
  swaps a login page into a `div`. Fix with an `HX-Redirect` response header on auth
  failures, handled centrally in the middleware.
- Double submission on slow connections — `hx-disabled-elt`.
- Very long recipe names must not break the layout; enforce wrapping and truncation.

## Security notes

- Django autoescaping stays on. Any use of `|safe` or `mark_safe` in a template must be
  justified in review — that is the one place XSS gets into an app like this.
- Nav visibility is not authorization. Every view still checks.
- No CDN, no third-party fonts, no analytics. Nothing on a page phones home.
