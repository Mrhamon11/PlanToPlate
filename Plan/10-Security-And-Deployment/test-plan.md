# 10 — Security & Deployment · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

Much of this task is verified operationally rather than by pytest. Both halves are mandatory —
the manual checklist is not optional garnish.

## Headers and settings — `config/tests/test_security_settings.py`

| Test | Asserts |
|---|---|
| `test_deploy_check_clean` | `manage.py check --deploy` under prod settings returns **zero** warnings. |
| `test_hsts_configured` | One year, subdomains, preload. |
| `test_ssl_redirect_enabled` | |
| `test_cookies_secure_and_httponly` | Session and CSRF. |
| `test_x_frame_options_deny` | |
| `test_content_type_nosniff` | |
| `test_referrer_policy` | |
| `test_allowed_hosts_not_wildcard` | `["*"]` in production fails the test. |
| `test_debug_false_in_prod` | |

## CSP — `config/tests/test_csp.py`

| Test | Asserts |
|---|---|
| `test_csp_header_present` | |
| `test_csp_has_no_unsafe_inline_script` | A CSP with `unsafe-inline` in `script-src` buys almost nothing. |
| `test_csp_frame_ancestors_none` | |
| `test_no_inline_event_handlers_in_templates` | Greps every template for `onclick=` and friends. |

## Throttling — `config/tests/test_throttling.py`

| Test | Asserts |
|---|---|
| `test_login_throttled` | Task 01's, re-verified. |
| `test_password_change_throttled` | |
| `test_import_throttled` | |
| `test_global_authenticated_throttle` | |
| `test_throttle_returns_429_with_retry_after` | |

## Authorization regression sweep — `core/tests/test_authorization_sweep.py`

The safety net for everything built in tasks 03–09.

| Test | Asserts |
|---|---|
| `test_every_owned_viewset_uses_visible_to` | Parametrized over **every** registered viewset. |
| `test_every_owned_view_uses_visible_to` | The HTML side too. |
| `test_every_owned_model_returns_404_not_403` | Parametrized over every owned model. |
| `test_no_serializer_exposes_owner_as_writable` | |
| `test_all_nested_serializers_filter_visibility` | |
| `test_anonymous_cannot_reach_any_data_endpoint` | Parametrized over every registered route. Catches the endpoint someone added without a permission class. |

## Input validation — `core/tests/test_input_validation.py`

| Test | Asserts |
|---|---|
| `test_all_text_fields_have_max_length` | Introspects every model; an unbounded `TextField` on a user-writable model fails. Cheap denial of service otherwise. |
| `test_decimal_fields_have_bounds` | |
| `test_oversized_payload_rejected` | |
| `test_json_fields_validated` | Profile `tag_limits` rejects an arbitrary structure. |

## Backups — `deploy/tests/test_backup.py`

| Test | Asserts |
|---|---|
| `test_backup_script_produces_valid_db` | The output opens and passes `PRAGMA integrity_check`. |
| `test_backup_uses_sqlite_backup_not_cp` | The script contains `.backup` and **not** a bare `cp` of the database. `cp` on a WAL database can capture a torn state that fails only when you need it. |
| `test_backup_checksummed` | |
| `test_retention_prunes_correctly` | Against a directory of dated fixtures. |
| `test_dumpdata_export_loads` | The JSON export round-trips into a clean database. |

## Restore — `deploy/tests/test_restore.py`

| Test | Asserts |
|---|---|
| `test_restore_produces_matching_counts` | Every model's row count matches the source. |
| `test_restore_then_migrate_succeeds` | Restoring an older schema and migrating forward works — the realistic disaster path. |

## Health and operations — `core/tests/test_ops.py`

| Test | Asserts |
|---|---|
| `test_healthz_reports_db` | |
| `test_checkpoint_wal_command` | Runs and shrinks the WAL. |
| `test_logging_excludes_passwords` | An auth request writes no credential to any handler. |

## Manual verification — mandatory

**Deployment**
1. Deploy to a clean target via Compose. The app serves over HTTPS with a valid certificate.
2. `DEBUG` is False **in the running container**, not merely in the file.
3. Static and media are served by Caddy, not Django.
4. Restart the host; the app comes back automatically with data intact.
5. Browse every page with devtools open — **zero CSP violations**.
6. Confirm `securityheaders.com` or an equivalent gives an A grade (or the reason it does not
   is understood and documented).

**Backups — the one that matters**

7. Run a backup. Confirm the file exists, is checksummed, and passes an integrity check.
8. **Perform a real restore into a scratch directory. Open the app against it. Confirm your
   recipes are there.** A backup that has never been restored is a hypothesis, not a backup.
9. Confirm retention pruning leaves the expected set.
10. Confirm the off-box copy actually lands off-box.

**Security spot checks**
11. Log in as a regular user and attempt to reach `/admin/` — denied.
12. Attempt to fetch another user's private recipe by ID — 404, not 403.
13. Exceed the login throttle — 429.
14. Confirm the session cookie is `Secure`, `HttpOnly`, `SameSite=Lax` in the browser.

## Definition of Done

- [ ] Every automated test above exists and passes.
- [ ] `manage.py check --deploy` under prod settings: **zero warnings**.
- [ ] CSP active with no `unsafe-inline`; zero violations across every page.
- [ ] The authorization sweep covers every registered viewset and route.
- [ ] `pip-audit` clean, or every finding documented with a reason.
- [ ] **A real restore was performed and verified** (manual check #8).
- [ ] Off-box backup copy confirmed working.
- [ ] `docs/OPERATIONS.md` covers every procedure in the design.
- [ ] All 14 manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated and **the MVP marked complete**.
