# N1 — Images & Camera · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **N1.1 — `Image` model**
  Nullable parent FKs with an exactly-one check constraint, UUID upload path, primary/position.
  *Files:* `images/models.py`

- [ ] **N1.2 — Validation pipeline**
  Size cap, content verification, format allowlist, SVG rejection, decompression-bomb cap.
  *Files:* `images/services/validate.py`
  *Done when:* every malicious fixture in the test plan is rejected.

- [ ] **N1.3 — Processing pipeline**
  Re-encode, strip EXIF, resize, thumbnail.
  *Files:* `images/services/process.py`
  *Done when:* a GPS-tagged photo comes out with no EXIF.

- [ ] **N1.4 — Storage configuration**
  `MEDIA_ROOT`, `django-storages` seam, Caddy media serving with `nosniff`.
  *Files:* `config/settings/*`, `Caddyfile`

- [ ] **N1.5 — Per-user quota**
  Enforced at upload with a clear message.
  *Files:* `images/services/quota.py`

- [ ] **N1.6 — Orphan cleanup**
  `post_delete` removing files; a management command to sweep existing orphans.
  *Files:* `images/signals.py`, `images/management/commands/clean_orphan_images.py`

- [ ] **N1.7 — API**
  Upload, list, reorder, set-primary, caption, delete.
  *Files:* `images/api.py`, `images/serializers.py`

- [ ] **N1.8 — Upload UI**
  Drop zone with tap fallback, client-side downscale, progress, named errors.
  *Files:* `templates/images/_partials/_upload.html`, `static/js/upload.js`

- [ ] **N1.9 — Camera capture**
  `capture="environment"` on the mobile input.
  *Files:* `templates/images/_partials/_upload.html`

- [ ] **N1.10 — Gallery UI**
  Reorder, set primary, caption, delete; lazy loading with explicit dimensions.
  *Files:* `templates/images/_partials/_gallery.html`

- [ ] **N1.11 — Attach images to existing screens**
  Recipe, dish, ingredient, book, and list detail pages and cards.
  *Files:* templates across apps

- [ ] **N1.12 — Media backups**
  Extend task 10's backup script to sync `MEDIA_ROOT`.
  *Files:* `deploy/backup.sh`
  *Done when:* a restore drill brings back both database and images.

- [ ] **N1.13 — Update the living document**
  *Files:* `Plan/MILESTONES.md`
