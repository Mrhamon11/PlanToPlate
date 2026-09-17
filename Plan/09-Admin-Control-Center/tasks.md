# 09 — Admin Control Center · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **09.1 — Custom `AdminSite`**
  Branding plus `has_permission` requiring `is_staff`, `is_active`, and no pending forced
  password change.

  **Deferred here from task 01:** `/admin/logout/` is not in
  `ForcePasswordChangeMiddleware`'s exemption set, so a staff user with a pending forced
  change who POSTs there is redirected to the change form instead of being logged out
  (`/accounts/logout/` works). Cosmetic, and this task's `has_permission` likely makes it
  moot — confirm that it does, or add the path to the exemption set.
  *Files:* `config/admin.py`, `config/urls.py`, `accounts/middleware.py`

  **Finding:** `has_permission` does **not** by itself make it moot — `ForcePasswordChange`
  `Middleware` runs before any admin view, so for a non-exempt path it still redirects
  `/admin/logout/` to the password-change form (the exact task-01 complaint). `admin:logout`
  was added to the middleware exemption set, matching the existing `accounts:logout` /
  `accounts_api:logout` exemptions. Note the tightened `has_permission` then makes
  `AdminSite.admin_view` redirect that same request to `/admin/` (its built-in "no permission
  + logout path" branch), so `/admin/logout/` still does not *complete* a logout for a
  forced-change user — but that user's working logout route, `/accounts/logout/`, is already
  exempt and unaffected. Fully fixing `/admin/logout/` would mean overriding `admin_view` /
  `AdminSite.logout`, which is out of proportion to the issue. `config/urls.py` needed no
  change: the custom `AdminSite` is wired via `config.apps.PlanToPlateAdminConfig`
  `.default_site`, so `admin.site.urls` already resolves to it.

- [x] **09.2 — Register every model**
  `ModelAdmin` for each with display, filters, search, `list_select_related`, and `raw_id_fields`.
  *Files:* `*/admin.py`
  *Done when:* every model is browsable and no changelist N+1s.

- [x] **09.3 — Inlines**
  Components, entries, and items under their parents.
  *Files:* `*/admin.py`

- [x] **09.4 — Cycle guard in the admin**
  `RecipeComponentInline.clean()` calling `assert_no_cycle`.
  *Files:* `recipes/admin.py`
  *Done when:* task 05's `test_guard_enforced_on_admin` passes.

  **Rework pass (2026-09-08, reviewer blocking #1 — resolved):** every admin `sub_recipe`
  write path (the inline form, the inline formset, and the standalone `RecipeComponentAdmin`
  form) was running the cycle/depth guard but *not* the sub-recipe unit-scalability guard that
  `recipes/serializers.py` and `core/services/importer.py` enforce — an admin could save a
  component whose `unit` cannot be scaled to its sub-recipe's `yield_unit`, which then 500s in
  the flattener (dish detail, shopping-list generate/preview). Fixed by lifting
  `recipes/services/components._assert_unit_scalable` to the public
  `assert_sub_recipe_unit_scalable` (the single implementation, CLAUDE.md §6) and calling it
  from `_ComponentXorCleanMixin.clean` — the mixin backs both the inline row form and the
  standalone form, so all four write paths are covered at form level (the check is purely
  per-row; the formset keeps only the parent-context cycle/depth guard). Tests added beside
  `test_cycle_guard_enforced_in_admin_inline` in `recipes/tests/test_admin.py`:
  `test_sub_recipe_unit_scalability_enforced_in_admin_inline`,
  `test_sub_recipe_unit_scalability_enforced_in_standalone_component_admin`,
  `test_admin_inline_accepts_a_scalable_sub_recipe_unit`.

- [x] **09.5 — Create-user flow**
  Custom form and view; temp password generated and shown once with a copy button.
  *Files:* `accounts/admin.py`, `accounts/services.py`, `templates/admin/create_user.html`,
  `core/services/audit.py`
  *Done when:* the password appears exactly once and is nowhere in the database or logs.

  Built: `accounts.services.create_user()` builds the `User`, calls task 01's
  `set_temp_password` (hash only, `must_change_password=True`, 7-day expiry), emits the
  `LogEntry` audit records (temp password issued; entitlement granted if staff), returns the
  plaintext for one-time display. The stock "Add user" button redirects to
  `admin:accounts_user_create`. The password never touches the DB, a log, or a reload of the
  page.

- [x] **09.6 — Reset-password action**
  Bulk admin action; new temp password, forced change, **all sessions invalidated**.
  Reuse task 01's `set_temp_password` — it already revokes DRF tokens and cycles the hash.

  **Deferred here from task 01:** `README.md` currently offers `manage.py changepassword` as
  the first-line admin recovery step. That command sets the hash directly, so it revokes no
  DRF token and leaves `must_change_password` alone — it contradicts design.md's invariant
  that every password-setting path routes through a service that revokes tokens. Harmless
  today (nothing mints tokens outside the admin), but reorder the README so
  `bootstrap_admin --force` leads and `changepassword` is documented as the last resort it is.
  *Files:* `accounts/admin.py`, `accounts/services.py`, `templates/admin/reset_password_done.html`,
  `README.md`

  Built: `reset_temp_password` admin action → `accounts.services.reset_password()` calls
  `set_temp_password` then `invalidate_sessions()` (iterates the DB session backend, deletes
  every row for the user — `set_password`'s hash cycle already fails the auth-hash check, this
  removes the rows outright), emits the audit record, and shows each new temp password once
  with a copy button. README recovery section reordered: `bootstrap_admin --force` leads,
  `changepassword` documented as a last resort with its gaps spelled out.

- [x] **09.7 — Delete-user preview**
  Per-model counts of what will be destroyed; requires typing the username to confirm.
  *Files:* `accounts/admin.py`, `accounts/services.py`, `lists/signals.py`,
  `templates/admin/delete_user_confirm.html`

  Built: `UserAdmin.delete_view` overridden — GET renders per-model CASCADE counts
  (`admin.utils.get_deleted_objects`), POST refuses unless `confirmation` matches the username
  exactly. Deletion routes through `accounts.services.delete_user()`, which runs the **D41
  reconciliation** first: `lists.signals.tombstone_items_for_owner_deletion(owner)` stamps
  fallback text on every content-only `ListItem` a cascade of that owner would leave
  content-less — including the two-FK (`ingredient` + `dish`) generated item on a bystander's
  list that the per-model `pre_delete` receivers each skip. Chosen over a two-FK branch in the
  receivers because it keeps the extra work off every recipe/dish/ingredient delete's hot path
  (the D41 note already frets about that side effect) and localises the fix to the one flow
  that triggers it. `delete_model` also routes through the service, and `get_actions` removes
  the stock bulk "delete selected" action entirely so no unguarded bulk-delete route survives
  (`delete_queryset` is therefore not overridden).

- [x] **09.8 — Admin entitlement**
  Toggle `is_staff`, with the last-admin guard on both demotion and deletion.
  *Files:* `accounts/admin.py`, `accounts/services.py`, `config/apps.py`,
  `accounts/management/commands/bootstrap_admin.py`
  *Done when:* the final admin cannot remove their own access by any route.

  Built: `accounts.services.set_entitlement()` (grant/revoke `is_staff`, no-op writes
  nothing, emits the audit record) + `is_last_admin()` / `active_admins()`. The guard blocks
  the last active admin on **every** route: the `revoke_admin` action, the change-form
  (`GuardedUserChangeForm.clean` — covers `is_staff` *and* `is_active`), the `delete_view`
  POST, and `delete_model`. `grant_admin` / `revoke_admin` bulk actions added; the stock
  bulk "delete selected" action is removed via `get_actions`.

  **Two items deferred here from task 01 — decisions made:**
  - **D26 — `bootstrap_admin --force` and the last-admin guard.** `--force` stays **outside**
    the guard: it is the documented recovery route for when the only admin is *already* locked
    out, and it is gated behind shell access (root-equivalent here). It now emits the same
    audit records as the UI (`Command._audit` → temp password issued + entitlement granted;
    `actor=None`, logged against the target). Plain `bootstrap_admin` (first-run create) emits
    them too.
  - **D29 — `authtoken.TokenProxy`.** **Unregistered** from the admin
    (`config.apps.PlanToPlateAdminConfig.ready`). `/admin/authtoken/tokenproxy/add/` minted a
    token for any user with no audit trail and no revocation semantics; nothing mints tokens
    through the UI yet (D24), so the admin has no business doing it. A future token-issuing
    flow gets its own audited endpoint, not this back door.

- [x] **09.9 — JSON import validator**
  Full dry-run validation producing path-qualified errors; caps enforced.
  *Files:* `core/services/importer.py`, `core/schemas.py`

  Built: `core/schemas.py` holds the format (version, sections, per-object required fields)
  and the DoS caps (5 MB / 1000 objects / depth 10 — size and depth checked off the raw text
  before `json.loads`). `core/services/importer.py::validate()` runs the whole dry run:
  parse → shape → object-count cap → resolve every unit / tag / ingredient / sub-recipe
  reference against the in-file objects and the owner's `.visible_to` set, returning an
  `ImportPlan` or raising `ImportValidationError` with one path-qualified `ImportProblem`
  (`recipes[3].components[1].unit: unknown unit 'cupp'`) per fault. In-file recipe cycles are
  caught here too. Writes nothing.

- [x] **09.10 — JSON import executor**
  Two-pass name resolution, atomic write, owner from the argument only, cycle guard applied,
  skip/update modes.
  *Files:* `core/services/importer.py`

  Built: `execute(plan, *, owner, actor, mode, dry_run)` — pass 1 creates every ingredient
  then every recipe *shell* then every dish, pass 2 wires components (so a recipe may
  reference a sub-recipe defined later); one `transaction.atomic()`, `dry_run` ends it with
  `set_rollback(True)`. `owner` is the argument only — no `owner` / `is_system` key in the
  file is ever read. `assert_no_cycle` runs before each imported sub-recipe edge; a
  `GraphError` rolls the whole import back. `--skip-existing` (default) / `--update-existing`
  match on `(owner, name)` case-insensitively. References resolve against
  `Ingredient/Recipe.objects.visible_to(owner)` only. **Audit (`test_import_logged`) is 09.13.**

  **Sub-note (2026-09-08, dev) — accepted import-format deviations from `design.md`, for the
  09.14 decision-log pass to ratify:**
  - The import format is a **superset** of the `design.md` example. Components also accept
    `sub_recipe` (required to satisfy this subtask's "cycle guard applied to imported
    recipes"); recipes/dishes also accept optional `instructions` / `description` / `role` /
    `prep_minutes` / `cook_minutes` / `is_staple` / `notes`. Unit references resolve by name
    **or** abbrev (matching `seed_catalog`'s dual-key lookup; the design example mixes `"g"`
    and `"cup"`).
  - Unknown keys in the payload (`owner`, `is_system`, anything else) are **silently ignored**,
    not rejected — this is what keeps `test_owner_in_payload_ignored` clean.
  - Imported dish→recipe links get `DishComponent.servings = 1` (the design dish format has no
    servings field).
  - `manage.py import_json` makes `--owner` **required** (design.md says it defaults to the
    importing admin — a shell command has no request user). The admin page still defaults to
    the logged-in admin.
  - Finding 3 from the review-findings file was resolved by **removing `delete_selected`** from
    `UserAdmin` rather than adding a typed-confirm step to bulk delete.
  - **(2026-09-08 rework)** `manage.py import_json` passes `actor=owner` to the import-audit
    record — a shell run has no request user, so the CLI's audit `LogEntry` shows the owner as
    the actor. Consistent with `bootstrap_admin`'s existing `actor=None` handling in
    `audit._log`.

- [x] **09.11 — Import admin page and management command**
  Upload form with dry-run preview, plus `manage.py import_json`.
  *Files:* `core/admin.py`, `templates/admin/import_json.html`,
  `core/management/commands/import_json.py`

  **Sub-note (2026-09-08):** `config/tests/test_admin_security.py` is still empty. Its
  import-upload cases (`test_import_upload_rejects_non_json`) land here. Its non-import cases
  — `test_admin_actions_require_post`, `test_admin_csrf_enforced`,
  `test_admin_urls_not_guessable_by_regular_user`, `test_no_raw_sql_endpoint_exists` — already
  apply to the 09.5–09.8 custom actions/views (CSRF middleware + `{% csrf_token %}`, actions
  POST via the changelist) but were out of the 09.5–09.8 run's test list; write the whole file
  here.

  **Rework pass (2026-09-08, address-now A):**
  `config/tests/test_admin_security.py::test_admin_urls_not_guessable_by_regular_user` now
  also asserts `admin:accounts_user_create` and `admin:accounts_user_delete` (the overridden
  delete view) return 302/403 for a non-staff user — they were already `admin_view`-gated;
  this locks it in.

  Built: `core.admin.import_json_view` + `ImportJSONForm` (`file`, `owner` as a real
  `ModelChoiceField`, `mode`, `dry_run` default on), mounted at `admin:core_import_json` by
  `PlanToPlateAdminSite.get_urls` and gated by `admin_site.admin_view`. `templates/admin/
  import_json.html` shows the path-qualified problems or the preview counts. `manage.py
  import_json <file> --owner <username> [--update-existing] [--dry-run]`. Both call
  `importer.run_import`, so they cannot drift (`test_management_command_matches_admin_page`).
  Whole `config/tests/test_admin_security.py` written (all five test-plan cases + an anon
  bounce + import-page gating).

- [x] **09.12 — Admin dashboard**
  Counts, recent activity, database and WAL size, quick links.
  *Files:* `templates/admin/plantoplate_index.html`, `config/admin.py`,
  `config/tests/test_admin_dashboard.py`

  Built: `PlanToPlateAdminSite.index` injects a `dashboard` context from
  `dashboard_context()` — user counts, per-model row counts (ordered by app), recent
  signups, recent `LogEntry` activity, the SQLite database + WAL file sizes, and quick links
  to the create-user and JSON-import pages. DB/WAL sizing is a module helper,
  `config.admin.database_file_sizes(connection=None)`: reads the path off the `default`
  connection, returns `None` for `:memory:` or a non-SQLite engine (Postgres degrades, does
  not crash), reports a missing `-wal` file as `0`. The index template is a new
  `admin/plantoplate_index.html` (via `index_template`) that extends the stock
  `admin/index.html` and prepends the dashboard module — the stock `admin/index.html` is not
  shadowed. Tests: `test_dashboard_renders`, `test_counts_accurate`, `test_db_size_reported`
  (both files), plus a non-file-database guard case.

- [x] **09.13 — Audit logging**
  `LogEntry` records for temp-password issue, entitlement change, and import.
  Cover `bootstrap_admin` and `bootstrap_admin --force` too — task 01 shipped them as
  temp-password issuers and entitlement granters with no audit trail at all.
  *Files:* `core/services/audit.py`, `accounts/management/commands/bootstrap_admin.py`
  *Done when:* no logged record contains a password.

  **Sub-note — pulled forward with 09.5–09.8 (2026-09-08):** `core/services/audit.py`
  exists; `record_temp_password_issued` / `record_entitlement_change` are emitted by the
  create-user flow (09.5), the reset-password action (09.6), the entitlement service and
  change-form (09.8), **and** both `bootstrap_admin` paths. Tests: `core/tests/test_audit.py`
  (incl. `test_no_password_in_any_log_entry`).

  **Closed (2026-09-08 rework):** `audit.record_import_run` logs *that* a bulk import was
  applied, with the per-section created/updated/skipped counts and nothing from the file
  (prefix `audit.BULK_IMPORT_RUN`, recorded against the owner account). It is called from
  `importer.execute` **inside** the import transaction, so a real run always leaves a trail
  and a dry run leaves none — and both entry points get it for free via `run_import`. Tests:
  `test_import_logged` (counts asserted, object names asserted absent), `test_dry_run_import_
  not_logged`, and `test_no_password_in_any_log_entry` now also runs an import.

  **Carried-forward review findings (2026-09-08, reviewer — deferred here by owner):**
  *All five addressed in the 2026-09-08 rework — see notes inline below.*
  - `accounts/services.py` — audit `LogEntry` writes sit outside the DB transaction:
    `create_user` calls `audit.record_*` after its `atomic()` block closes; `reset_password`
    has no wrapping transaction at all. A failed `LogEntry` insert then leaves the
    temp-password issue / entitlement grant committed with no trail (and `create_user_view`
    500s on an issued-but-undisplayed password). Wrap service body + audit calls in one
    `transaction.atomic()`.
  - `accounts/services.py` `invalidate_sessions` — scans the whole `django_session` table and
    deletes rows during `.iterator()`. Fine on SQLite at this scale; a Postgres-portability
    smell. Collect the keys first, then one `filter(pk__in=...).delete()`.
  - `config/tests/test_admin.py` `_build_lists_listitem` — builds rows with `text=` only and
    all content FKs null, so the `ListItem` N+1 guard never exercises `list_select_related`
    (dropping it wouldn't fail `test_changelist_query_count_bounded`). Give the builder a
    shared non-null `list` / `recipe` / `unit`.
  - `accounts/tests/test_admin_users.py::test_last_admin_cannot_be_demoted` /
    `test_last_admin_cannot_be_deleted` — the form-path assertion is only "re-rendered +
    flag unchanged"; an unrelated validation failure would also pass. Assert the guard's
    error text.
  - `accounts/admin.py` `save_model` — toggles `is_staff` and audits inline rather than
    routing through `services.set_entitlement` (the last-admin guard is separately covered by
    `GuardedUserChangeForm.clean`). Minor logic-outside-services deviation; fold into the
    audit-logging cleanup or record as accepted.
    → **Accepted as a deviation (2026-09-08).** By the time `save_model` runs the change form
    has already written the new `is_staff` onto the instance, so `set_entitlement` (which
    no-ops when the requested value equals the current one) would record nothing. Un-mutating
    and re-applying through the service is more fragile than the two-line inline audit call,
    which still goes through the same `audit.record_entitlement_change` helper. The guard for
    this path stays in `GuardedUserChangeForm.clean`. Docstring on `save_model` explains it.

  **Rework resolutions (2026-09-08):**
  - `create_user` / `reset_password` — service body + `audit.record_*` calls now share one
    `transaction.atomic()` each; a failed `LogEntry` insert rolls the password issue back.
  - `invalidate_sessions` — collects session keys first, then one
    `Session.objects.filter(pk__in=...).delete()` (no delete during `.iterator()`).
  - `config/tests/test_admin.py::_build_lists_listitem` — now builds each row with a shared
    non-null `recipe` / `dish` / `ingredient` / `unit`, so the `ListItem` N+1 guard fails if
    `list_select_related` is dropped.
  - `test_last_admin_cannot_be_demoted` — asserts `b"only active admin"` in the re-rendered
    response (the guard's own message), not just "flag unchanged".

  **Rework pass (2026-09-08, reviewer findings — all resolved):**
  - **Blocking — importer was a third `RecipeComponent` write path skipping the sub-recipe
    unit-scalability guard.** `_Resolver` now indexes every sub-recipe's `yield_unit` (visible
    rows at construction, in-file recipes in `build_plan`); `_component_spec` calls
    `_sub_recipe_unit_scalable`, which runs `catalog.services.units.convert(quantity, unit,
    yield_unit)` and appends a path-qualified `ImportProblem` (`recipes[i].components[j].unit`)
    on `IncompatibleUnits` — the same guard `recipes/serializers.py` and
    `recipes/services/components.py` enforce, at validation time. Tests:
    `test_incompatible_sub_recipe_unit_reports_path` (in-file + existing sub-recipe),
    `test_compatible_sub_recipe_unit_passes` in `core/tests/test_import_validation.py`.
  - **NB — `bootstrap_admin` `_audit` outside `atomic()`.** `_create` now wraps
    `set_temp_password` + `_audit` in one `transaction.atomic()`; `_reset` moves `_audit`
    inside its existing block. A failed `LogEntry` insert rolls the password issue back.
  - **NB — `revoke_admin` action loop had no transaction.** Wrapped in `transaction.atomic()`
    so a `LastAdminError` part-way through rolls back the demotions already applied.
  - **NB — D29 `TokenProxy` unregister had no test.**
    `config/tests/test_admin_security.py::test_token_proxy_not_registered_in_admin` asserts
    `TokenProxy not in admin.site._registry` and `admin:authtoken_tokenproxy_add` raises
    `NoReverseMatch`.
  - **NB — `import_json_view` caught only `ImportValidationError`.** `core/schemas.py`
    `_decimal_or_problem` now takes the target `DecimalField` and rejects an out-of-range
    magnitude as a path-qualified problem (`DecimalValidator`, bounds read off
    `Recipe.yield_quantity` / `RecipeComponent.quantity`). The view adds a broad `except
    Exception` (logs, surfaces a problem-list entry). Tests:
    `test_quantity_magnitude_cap_enforced`,
    `test_import_upload_surfaces_unexpected_error_as_problem`.

- [x] **09.14 — Update the living document**
  Task 09 → AWAITING APPROVAL. Resolve the ingredient-promotion open question from
  `MILESTONES.md` §8.
  *Files:* `Plan/MILESTONES.md`

  **Sub-note (2026-09-08, tester):** `MILESTONES.md` still shows Task 09 `NOT STARTED` —
  that update belongs here, at task completion, not to the 09.1–09.8 partial run. Also carry
  the test-plan's **Manual verification** items into the completion checklist: 1, 2, 4, 5
  (create-user temp-password login, reset-password session kill, last-admin demotion refusal,
  delete-user preview counts) exercise the 09.5–09.8 flows and are not yet performed/reported;
  item 3 lands with the importer (09.9–09.11). DoD "All five manual verifications performed
  and reported" stays unticked until then.

  **Carried-forward review findings (2026-09-08, reviewer — deferred here by owner):**
  - **Importer shape-validates before the object-count cap.** *Resolved in the rework pass
    (2026-09-08): `core/services/importer.py::validate()` now carries a comment stating the
    ordering is deliberate and bounded by the 5 MB byte cap checked first (a count-first
    reorder would need `validate_shape`'s non-dict-top-level guard duplicated). No longer a
    09.14 item.*
  - **`config/admin.py` `_human_bytes` uses `float`.** CLAUDE.md §3 says never `float`, but
    this is byte-count *display* formatting — never a measured quantity, never persisted or
    compared. Accepted; *the one-line explanatory comment was added in the 2026-09-08 rework
    pass* (`config/admin.py::_human_bytes`). The acceptance still needs noting in the
    completion handoff / decision log (09.14).
  - **Uneven per-app admin search-test coverage.** Only `recipes/tests/test_admin.py` has a
    `test_search_works`; `meals` / `lists` / `catalog` / `planner` set `search_fields` but
    exercise them only through the generic `test_changelist_loads_for_each_model`. Add a
    small parametrized search smoke test in `config/tests/test_admin.py` covering every
    registered model with `search_fields` (a `search_fields` entry naming a renamed field
    raises `FieldError` only when a search actually runs).

  **Sub-note (2026-09-08, rework — dashboard DB-size panel):** the test DB is `:memory:`
  (`config/settings/test.py`), so `config.admin.database_file_sizes()` returns `None` under
  the test client and the dashboard's DB + WAL size panel degrades to "reported for a
  file-backed SQLite database only". The helper itself is unit-tested directly against temp
  files (`test_db_size_reported`, plus the WAL-absent and non-file-DB cases), but the panel
  rendering **with real numbers** is only exercisable in manual verification against a real
  deployment — add a sixth manual-verification check here: "open `/admin/` on a file-backed
  DB and confirm the database + WAL sizes show."

  **Closed (2026-09-17).** Ingredient-promotion open question resolved in `ARCHITECTURE.md`'s
  Open Questions section: already answered by the existing generic admin edit access
  (`catalog.admin.IngredientAdminForm` keeps `owner`/`is_system`/`visibility` editable), no
  dedicated feature needed. `_human_bytes` float acceptance recorded as `ARCHITECTURE.md` D54.
  All six manual verifications (the five from `test-plan.md` plus the dashboard DB-size sixth
  check) performed via `dev-test-walkthrough.md` (kept, not deleted — owner wants it around for
  reuse) and recorded in `test-plan.md`'s Manual verification section for a durable record. The
  walkthrough's live delete-user pass surfaced a real bug (D53's migrations not yet applied on
  the dev-test box) — fixed by applying them; see `test-plan.md` for the full account and
  [`../11-TaskBugFixes/tasks.md`](../11-TaskBugFixes/tasks.md) 11.32–11.34 for the review
  findings deferred rather than fixed in-task. `Plan/MILESTONES.md`'s task 09 row updated; task
  set to `COMPLETE`.
