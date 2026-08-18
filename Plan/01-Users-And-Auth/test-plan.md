# 01 — Users & Authentication · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Unit — `accounts/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_user_model_is_custom` | `get_user_model()` is `accounts.User`. |
| `test_new_user_defaults` | `must_change_password` False, `temp_password_expires_at` None. |
| `test_password_is_hashed` | The stored value is not the plain text and `check_password` succeeds. |

## Unit — `accounts/tests/test_services.py`

| Test | Asserts |
|---|---|
| `test_generate_temp_password_length_and_charset` | At least 12 characters, URL-safe. |
| `test_generate_temp_password_is_unique` | 100 generations produce 100 distinct values. |
| `test_set_temp_password_sets_flags` | `must_change_password` True and expiry ≈ now + 7 days. |
| `test_temp_password_not_stored_plaintext` | The plain value appears in no column of the row. |
| `test_complete_password_change_clears_flags` | Both fields cleared, new password valid. |
| `test_complete_password_change_is_atomic` | A failure mid-way leaves the old password working. |

## Integration — `accounts/tests/test_auth_flow.py`

| Test | Asserts |
|---|---|
| `test_login_success_redirects_to_home` | |
| `test_login_wrong_password_fails` | 200 with a form error, not authenticated. |
| `test_login_nonexistent_user_same_message` | The error text is byte-identical to the wrong-password case. Different messages are a user-enumeration oracle. |
| `test_logout_requires_post` | GET returns 405. A GET logout can be fired from any `<img>` on any site. |
| `test_logout_clears_session` | |
| `test_session_survives_browser_close` | Cookie has an explicit `max-age`, not a session cookie. |
| `test_session_is_rolling` | Session expiry advances on a later request. |
| `test_session_cookie_httponly_and_samesite` | |

## Integration — `accounts/tests/test_forced_password_change.py`

| Test | Asserts |
|---|---|
| `test_temp_password_user_redirected_to_change` | Any app URL redirects to the change form. |
| `test_change_form_itself_not_redirected` | No loop. |
| `test_logout_not_redirected` | A user forced to change can still leave. |
| `test_after_change_normal_access_restored` | |
| `test_expired_temp_password_rejected` | Login refused with the expiry message. |
| `test_api_returns_403_not_redirect` | `/api/` gives `{"detail": "password_change_required"}`, not HTML. |
| `test_session_cycled_on_password_change` | The pre-change session key no longer authenticates. **This is the test that proves a stolen session dies at reset.** |
| `test_static_and_healthz_exempt` | |

## Integration — `accounts/tests/test_api.py`

| Test | Asserts |
|---|---|
| `test_api_login_sets_session` | |
| `test_me_returns_current_user` | Includes `must_change_password`; excludes `password`. |
| `test_me_requires_auth` | 403 anonymous. |
| `test_api_password_change_requires_old_password` | |
| `test_no_endpoint_leaks_password_hash` | Every auth response body is scanned for `password` and for the hash prefix. |

## Security — `accounts/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_login_throttled_after_five_attempts` | The 6th within a minute is 429. |
| `test_throttle_does_not_lock_the_account` | After the window, the real password still works. A throttle that locks accounts hands an attacker a DoS. |
| `test_no_registration_url_exists` | Reversing common signup route names fails, and no URL pattern contains "signup"/"register". |
| `test_password_min_length_enforced` | A 9-character password is rejected. |
| `test_password_not_in_logs` | With logging captured, a login attempt writes no plain-text password. |

## Management command — `accounts/tests/test_commands.py`

| Test | Asserts |
|---|---|
| `test_bootstrap_admin_creates_superuser` | Created with `must_change_password=True` and the temp password printed. |
| `test_bootstrap_admin_idempotent` | A second run creates nothing and exits 0 with a message. |

## Manual verification

1. Bootstrap an admin, log in with the temp password, confirm the forced-change screen appears
   and that no other page is reachable until it is done.
2. Log in, close the browser entirely, reopen it — still logged in. Click logout — logged out.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] `uv run pytest` green; `ruff` clean.
- [ ] `AUTH_USER_MODEL` is `accounts.User` and migrations apply on a fresh database.
- [ ] Both manual verifications performed and reported.
- [ ] No plain-text password is stored, logged, or returned anywhere.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
