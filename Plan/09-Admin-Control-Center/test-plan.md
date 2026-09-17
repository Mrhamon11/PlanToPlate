# 09 — Admin Control Center · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Access control — `config/tests/test_admin_access.py`

| Test | Asserts |
|---|---|
| `test_anonymous_redirected_to_login` | |
| `test_regular_user_denied` | A non-staff authenticated user gets no admin access. |
| `test_staff_user_allowed` | |
| `test_inactive_staff_denied` | |
| `test_staff_with_pending_password_change_denied` | An admin mid-forced-reset administers nothing. |
| `test_every_model_registered` | Introspect all app models; each is registered. Catches the model added in a later task that nobody registered. |

## Model admins — `*/tests/test_admin.py`

| Test | Asserts |
|---|---|
| `test_changelist_loads_for_each_model` | Parametrized over every registered model. |
| `test_changelist_query_count_bounded` | No N+1 on a 50-row changelist. |
| `test_search_works` | |
| `test_cycle_guard_enforced_in_admin_inline` | Saving a cyclic component through the admin is rejected. The third of task 05's three write paths. |

## User management — `accounts/tests/test_admin_users.py`

| Test | Asserts |
|---|---|
| `test_create_user_generates_temp_password` | `must_change_password=True`, expiry set. |
| `test_temp_password_displayed_once` | Present on the success response, absent on a reload. |
| `test_temp_password_not_stored` | The plain value appears in no column. |
| `test_temp_password_not_logged` | With logging captured. |
| `test_created_user_can_log_in_with_temp_password` | End to end into the forced-change screen. |
| `test_reset_password_action` | New temp value, flags set. |
| `test_reset_invalidates_sessions` | The user's existing session no longer authenticates. **Resetting a possibly-compromised password is pointless if the attacker's session survives.** |
| `test_delete_preview_shows_counts` | Per-model counts of what will be destroyed. |
| `test_delete_requires_typed_confirmation` | Wrong text → no deletion. |
| `test_delete_cascades_owned_objects` | |
| `test_delete_preserves_others_copies` | `copied_from` nulled, copy intact. |
| `test_entitle_admin_sets_staff` | |
| `test_last_admin_cannot_be_demoted` | |
| `test_last_admin_cannot_be_deleted` | Locking yourself out of a self-hosted app has no recovery path. |
| `test_admin_cannot_view_existing_password` | No admin view exposes a hash or plain text. |

## Import validation — `core/tests/test_import_validation.py`

| Test | Asserts |
|---|---|
| `test_valid_file_passes` | |
| `test_unknown_unit_reports_path` | `recipes[3].components[1].unit`. A bare "invalid file" is unusable against a 400-line import. |
| `test_unknown_tag_reports_path` | |
| `test_missing_required_field_reports_path` | |
| `test_duplicate_name_in_file_rejected` | Ambiguous references. |
| `test_file_size_cap_enforced` | Over 5 MB rejected before parsing. |
| `test_object_count_cap_enforced` | |
| `test_nesting_depth_cap_enforced` | Guards against a deeply-nested parser bomb. |
| `test_malformed_json_reports_position` | |
| `test_unknown_version_rejected` | |
| `test_validation_writes_nothing` | The database is untouched by a failed validation. |

## Import execution — `core/tests/test_import_execution.py`

| Test | Asserts |
|---|---|
| `test_import_creates_objects` | |
| `test_import_is_atomic` | One bad object → **nothing** is created. |
| `test_forward_references_resolved` | A recipe referencing a sub-recipe defined later in the file. |
| `test_owner_set_from_argument` | |
| `test_owner_in_payload_ignored` | A file claiming `"owner": "admin"` cannot escalate or forge attribution. **The key import security test.** |
| `test_is_system_in_payload_ignored` | |
| `test_cycle_in_import_rejected` | |
| `test_skip_existing_default` | |
| `test_update_existing_mode` | |
| `test_dry_run_writes_nothing` | |
| `test_import_resolves_against_visible_objects_only` | Referencing another user's private ingredient by name does not bind to it. |
| `test_management_command_matches_admin_page` | Both paths produce identical results — otherwise one of them will drift and be the untested one. |

## Audit — `core/tests/test_audit.py`

| Test | Asserts |
|---|---|
| `test_temp_password_issue_logged` | |
| `test_entitlement_change_logged` | |
| `test_import_logged` | With counts. |
| `test_no_password_in_any_log_entry` | Scans every `LogEntry` message. |

## Dashboard — `config/tests/test_admin_dashboard.py`

| Test | Asserts |
|---|---|
| `test_dashboard_renders` | |
| `test_counts_accurate` | |
| `test_db_size_reported` | Including the WAL file — an operational signal that matters on SQLite. |

## Security — `config/tests/test_admin_security.py`

| Test | Asserts |
|---|---|
| `test_no_raw_sql_endpoint_exists` | No admin URL accepts arbitrary SQL. **Deliberately not built** — it would be a remote code execution primitive on a home server. |
| `test_admin_actions_require_post` | |
| `test_admin_csrf_enforced` | |
| `test_import_upload_rejects_non_json` | |
| `test_admin_urls_not_guessable_by_regular_user` | Every admin URL returns 403/302 for a non-staff user. |

## Manual verification

1. Create a user, copy the temp password, log in as them in a private window, complete the
   forced change, confirm normal access.
2. Reset that user's password while they are logged in elsewhere; confirm the other session is
   dead.
3. Import a hand-written 20-recipe JSON file; then re-import it and confirm nothing duplicates.
4. Attempt to demote the only admin and confirm it is refused.
5. Preview deleting a user with content and confirm the counts are accurate.

**Performed and reported (2026-09-17), on `fedora-headless`'s file-backed dev-test DB** — the
click-through was `Plan/09-Admin-Control-Center/dev-test-walkthrough.md` (owner-run, kept in
the repo for reuse rather than deleted; this note is the durable record for the DoD):

1. **Create-user temp-password login** — verified (walkthrough Scenario 3): password shown
   once, absent on reload and in every admin view; `testuser1`/`testuser2` created and logged
   in with the temp value, forced into the change screen.
2. **Reset-password session kill** — verified (Scenario 4): the logged-in second session was
   dead immediately after the reset action.
3. **Bulk JSON import round-trip** — verified (Scenario 10 steps 1–6, hand-run): dry-run
   preview, real import, re-import skip-existing (no duplicates), update-existing. Steps 7–10
   (owner-forgery, path-qualified error cases) and Scenario 11 (management command) were
   verified by the automated suite instead of by hand, per the walkthrough's own note, since
   they're exhaustively covered by `core/tests/test_import_execution.py` /
   `test_import_validation.py`.
4. **Last-admin demotion refusal** — verified (Scenario 7): all four routes (bulk action,
   change-form `is_staff` untick, change-form `is_active` untick, delete) refused on the sole
   remaining admin.
5. **Delete-user preview counts** — verified (Scenario 6), and this pass **found and fixed a
   real bug**: the D53 PROTECT-clearing pre-pass (self-owned + cross-owner `DishComponent`/
   `RecipeComponent` neutralization) initially threw `IntegrityError` on the dev-test box
   because its two new migrations (`meals.0002`, `recipes.0004`) hadn't been applied there yet
   — a schema gap, not a logic bug. Applied (with a `db.sqlite3` backup taken first), re-verified:
   delete-user now succeeds against a real self-owned-component account without the "protected"
   refusal. A related unshare report during the same session turned out to be unrelated —
   reproduced end to end against the test DB and confirmed `RecipeUnshareView` works correctly.
6. **Dashboard DB/WAL size panel** (added as a sixth check, `tasks.md` 09.14 sub-note) —
   verified (Scenario 2) against the real file-backed database; both panels render actual
   non-zero sizes.

## Definition of Done

- [x] Every test above exists and passes.
- [x] `ruff` clean; suite green; no pending migrations.
- [x] Every model is registered and browsable without N+1.
- [x] Temp passwords are shown once, never stored, never logged.
- [x] The last admin cannot be locked out by any route.
- [x] Import is atomic, path-qualified in its errors, and cannot set `owner`.
- [x] No arbitrary SQL execution exists anywhere in the admin.
- [x] All five manual verifications performed and reported.
- [x] The ingredient-promotion open question in `MILESTONES.md` §8 is resolved and recorded.
- [x] Subtasks ticked; `../MILESTONES.md` updated.
