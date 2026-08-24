# 02 — UI Shell · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **02.1 — Base template**
  `base.html` with head, meta viewport, nav include, messages container, content block,
  vendored script tags.
  *Files:* `templates/base.html`
  *Done when:* a trivial view extending it renders valid HTML.

- [ ] **02.2 — CSS design tokens and reset**
  Custom properties, dark-mode token overrides, a small modern reset, `.container`.
  *Files:* `static/css/reset.css`, `static/css/app.css`
  *Done when:* both colour schemes render legibly.

- [ ] **02.3 — Component CSS**
  Buttons, forms, cards, tables, badges, modal, empty state, spinner. All tap targets ≥44px.
  *Files:* `static/css/components.css`

- [ ] **02.4 — Responsive navigation**
  Desktop top bar, mobile bottom tab bar, overflow menu, `is_staff`-conditional admin link.
  *Files:* `templates/_partials/_nav.html`, `static/css/nav.css`
  *Done when:* usable at 375px and 1440px with no horizontal scroll.

- [ ] **02.5 — Shared partials**
  `_messages`, `_form_field`, `_pagination`, `_empty_state`, `_confirm_delete`.
  *Files:* `templates/_partials/*.html`

- [ ] **02.6 — HTMX and Alpine setup**
  Vendor both libraries into `static/js/`. `htmx` request-flag middleware, CSRF header on
  `<body>`, indicator styles.
  *Files:* `static/js/*`, `core/middleware.py`, `templates/base.html`
  *Done when:* `request.htmx` is True only for `HX-Request` requests.

- [ ] **02.7 — View mixins**
  `HtmxTemplateMixin`, `MessageMixin`, and a stub `OwnedObjectMixin` for task 03.
  *Files:* `core/views.py`, `core/mixins.py`
  *Done when:* one view renders full-page and fragment from a single class.

- [ ] **02.8 — HTMX-aware auth redirect**
  Return `HX-Redirect` instead of a 302 when an HTMX request hits a login-required view.
  *Files:* `core/middleware.py`
  *Done when:* an expired session during an HTMX action sends the browser to login rather
  than swapping a login form into a fragment.

- [ ] **02.9 — Restyle the task 01 auth templates**
  Bring login, logout, password change, and profile onto `base.html`.
  *Files:* `templates/accounts/*.html`

- [ ] **02.10 — Home / dashboard shell**
  Landing page after login with placeholder cards for the sections tasks 04–08 will fill.
  *Files:* `core/views.py`, `templates/core/home.html`, `config/urls.py`

- [ ] **02.11 — Error pages**
  Styled 403, 404, 429, 500 extending `base.html`. 500 must not depend on a context processor
  that could itself be the thing that failed.

  **429 is deferred here from task 01.** Login throttling shipped in 01.8, but the HTML login
  view and `/admin/login/` return the 429 as `HttpResponse(content_type="text/plain")` — a
  bare wall of text at the moment a real user has fat-fingered their password five times. Give
  it a template that says what happened, how long to wait, and that no account has been locked.
  Keep the `Retry-After` header the throttle already sets, and surface the same number in the
  body.
  *Files:* `templates/403.html`, `404.html`, `429.html`, `500.html`, `accounts/views.py`

- [ ] **02.12 — Update the living document**
  Task 02 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
