# N4 — PWA & Polish · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **N4.1 — Web app manifest**
  Icons including maskable, standalone display, theme colours, shortcuts to Shopping List and
  Meal Planner.
  *Files:* `static/manifest.json`, `templates/base.html`

- [ ] **N4.2 — Service worker: shell precache**
  Versioned caches with cleanup on activate.
  *Files:* `static/js/sw.js`

- [ ] **N4.3 — Service worker: fetch strategies**
  Network-first HTML, cache-first static, **never** cache API mutations.
  *Files:* `static/js/sw.js`

- [ ] **N4.4 — Update prompt and kill switch**
  "New version available" rather than a silent swap; an unregister path for recovery.
  *Files:* `static/js/sw-register.js`
  *Done when:* a bad worker can be recovered from without clearing browser data by hand.

- [ ] **N4.5 — Offline shopping list**
  Cache the default list; queue check-offs in IndexedDB; replay on reconnect.
  *Files:* `static/js/offline.js`

- [ ] **N4.6 — Cache clearing on logout**
  All caches and IndexedDB wiped.
  *Files:* `static/js/sw-register.js`, `accounts/views.py`
  *Done when:* a second user on the same device sees nothing of the first.

- [ ] **N4.7 — Cook mode**
  Large text, wake lock, step-by-step navigation.
  *Files:* `templates/recipes/cook_mode.html`

- [ ] **N4.8 — Global search**
  One box across recipes, dishes, books, and ingredients, visibility-filtered.
  *Files:* `core/views.py`, `templates/core/search.html`

- [ ] **N4.9 — Keyboard shortcuts**
  With a discoverable help overlay.
  *Files:* `static/js/shortcuts.js`

- [ ] **N4.10 — Loading, empty, and error states**
  Audit every screen; add what is missing, including retry actions.
  *Files:* across templates

- [ ] **N4.11 — Optimistic UI**
  Check-offs and favourite toggles, with rollback on failure.
  *Files:* `static/js/optimistic.js`

- [ ] **N4.12 — Accessibility audit**
  Keyboard, screen reader, contrast, and HTMX focus management across every screen.
  *Files:* across templates

- [ ] **N4.13 — Performance pass**
  Lighthouse, query-count regression tests, asset minification and cache headers.
  *Files:* various

- [ ] **N4.14 — Recently viewed**
  *Files:* `core/views.py`, `templates/core/home.html`

- [ ] **N4.15 — Update the living document**
  **Project complete.**
  *Files:* `Plan/MILESTONES.md`
