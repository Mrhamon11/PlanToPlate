# N3 — Social Feed · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **N3.1 — `Post` model**
  On `OwnedModel`, reusing `visibility`/`shared_with` as the audience. Task 03 hooks.
  *Files:* `social/models.py`

- [ ] **N3.2 — `PostAttachment` model**
  Nullable FKs with an exactly-one constraint, ordering.
  *Files:* `social/models.py`

- [ ] **N3.3 — Post creation service**
  Validates attachments are postable, calls task 03's `share()` for the audience, atomic,
  refuses with the blocker named when the cascade cannot grant.
  *Files:* `social/services.py`
  *Done when:* no new visibility logic exists in this app.

- [ ] **N3.4 — Feed query**
  `visible_to`, newest first, cursor pagination, prefetched attachments.
  *Files:* `social/managers.py`
  *Done when:* the feed query count is flat regardless of page size.

- [ ] **N3.5 — API**
  Post CRUD, feed, profile feed, copy-attachment passthrough.
  *Files:* `social/api.py`, `social/serializers.py`

- [ ] **N3.6 — Feed UI**
  Cards, attachment previews, per-object copy buttons, infinite scroll with a load-more
  fallback.
  *Files:* `templates/social/feed.html`, `_partials/_post_card.html`

- [ ] **N3.7 — Compose UI**
  Body, attachment picker filtered to postable objects, audience selector, and the explicit
  disclosure warning.
  *Files:* `templates/social/compose.html`
  *Done when:* the warning names the exact objects and the exact audience.

- [ ] **N3.8 — Post detail and profile feed**
  *Files:* `templates/social/post_detail.html`, `profile_feed.html`

- [ ] **N3.9 — Rate limiting**
  20 posts per hour.
  *Files:* `social/api.py`

- [ ] **N3.10 — Update the living document**
  Record the no-revoke-on-delete decision and the comments/likes exclusion.
  *Files:* `Plan/MILESTONES.md`
