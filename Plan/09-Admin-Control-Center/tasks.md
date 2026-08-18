# 09 — Admin Control Center · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **09.1 — Custom `AdminSite`**
  Branding plus `has_permission` requiring `is_staff`, `is_active`, and no pending forced
  password change.
  *Files:* `config/admin.py`, `config/urls.py`

- [ ] **09.2 — Register every model**
  `ModelAdmin` for each with display, filters, search, `list_select_related`, and `raw_id_fields`.
  *Files:* `*/admin.py`
  *Done when:* every model is browsable and no changelist N+1s.

- [ ] **09.3 — Inlines**
  Components, entries, and items under their parents.
  *Files:* `*/admin.py`

- [ ] **09.4 — Cycle guard in the admin**
  `RecipeComponentInline.clean()` calling `assert_no_cycle`.
  *Files:* `recipes/admin.py`
  *Done when:* task 05's `test_guard_enforced_on_admin` passes.

- [ ] **09.5 — Create-user flow**
  Custom form and view; temp password generated and shown once with a copy button.
  *Files:* `accounts/admin.py`, `templates/admin/create_user.html`
  *Done when:* the password appears exactly once and is nowhere in the database or logs.

- [ ] **09.6 — Reset-password action**
  Bulk admin action; new temp password, forced change, **all sessions invalidated**.
  *Files:* `accounts/admin.py`

- [ ] **09.7 — Delete-user preview**
  Per-model counts of what will be destroyed; requires typing the username to confirm.
  *Files:* `accounts/admin.py`, `templates/admin/delete_user_confirm.html`

- [ ] **09.8 — Admin entitlement**
  Toggle `is_staff`, with the last-admin guard on both demotion and deletion.
  *Files:* `accounts/admin.py`
  *Done when:* the final admin cannot remove their own access by any route.

- [ ] **09.9 — JSON import validator**
  Full dry-run validation producing path-qualified errors; caps enforced.
  *Files:* `core/services/importer.py`, `core/schemas.py`

- [ ] **09.10 — JSON import executor**
  Two-pass name resolution, atomic write, owner from the argument only, cycle guard applied,
  skip/update modes.
  *Files:* `core/services/importer.py`

- [ ] **09.11 — Import admin page and management command**
  Upload form with dry-run preview, plus `manage.py import_json`.
  *Files:* `core/admin.py`, `templates/admin/import_json.html`,
  `core/management/commands/import_json.py`

- [ ] **09.12 — Admin dashboard**
  Counts, recent activity, database and WAL size, quick links.
  *Files:* `templates/admin/index.html`, `config/admin.py`

- [ ] **09.13 — Audit logging**
  `LogEntry` records for temp-password issue, entitlement change, and import.
  *Files:* `core/services/audit.py`
  *Done when:* no logged record contains a password.

- [ ] **09.14 — Update the living document**
  Task 09 → AWAITING APPROVAL. Resolve the ingredient-promotion open question from
  `MILESTONES.md` §8.
  *Files:* `Plan/MILESTONES.md`
