# 01 — Users & Authentication · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [x] **01.1 — Custom user model**
  `accounts.User(AbstractUser)` with `must_change_password` and `temp_password_expires_at`.
  Set `AUTH_USER_MODEL`. Generate and read the initial migration before applying it.
  *Files:* `accounts/models.py`, `accounts/migrations/0001_initial.py`, `config/settings/base.py`
  *Done when:* `migrate` succeeds on a fresh database and `get_user_model()` returns `accounts.User`.

  > Do this before anything else in the project creates a user foreign key.

- [x] **01.2 — Session configuration**
  The session settings block from the design, secure flags gated to prod.
  *Files:* `config/settings/base.py`, `config/settings/prod.py`
  *Done when:* the settings tests in the test plan pass.

- [x] **01.3 — Password validators**
  Django's four defaults with `min_length=10`.
  *Files:* `config/settings/base.py`

- [x] **01.4 — Temp password service**
  `accounts/services.py`: `generate_temp_password()`, `set_temp_password(user)`,
  `complete_password_change(user, new_password)`.
  *Files:* `accounts/services.py`
  *Done when:* generation uses `secrets`, and completion clears both fields inside one transaction.

- [x] **01.5 — Forced password change middleware**
  `ForcePasswordChangeMiddleware` with the exempt-path list. HTML → redirect, `/api/` → 403 JSON.
  *Files:* `accounts/middleware.py`, `config/settings/base.py`
  *Done when:* no redirect loop, and the API branch returns JSON rather than HTML.

- [x] **01.6 — HTML auth views and templates**
  Login, logout (POST only), password change, profile. Templates extend the base from task 02;
  until that lands, a minimal standalone template is acceptable and gets restyled there.
  **The password-change view must call `update_session_auth_hash(request, user)` immediately
  after `complete_password_change`** — `set_password` alone flushes every session for the user,
  including the one making the request (see design.md, "Temp password flow" step 4); without
  this call the forced-reset flow ends by logging the user out instead of into the app.
  *Files:* `accounts/views.py`, `accounts/urls.py`, `templates/accounts/*.html`
  *Done when:* the full login → forced change → app flow works in a browser.

  Mount logout under the URL name `accounts:logout`. `ForcePasswordChangeMiddleware`
  reverses that name to build its logout exemption and falls back to a hardcoded
  `LOGOUT_PATH` while it does not resolve — a user forced to change their password cannot
  log out if the exemption misses. Once it is mounted, delete `LOGOUT_PATH` and the
  `test_logout_exemption_matches_hardcoded_fallback` self-check, which skips until then.

- [x] **01.7 — API auth endpoints**
  `login`, `logout`, `me`, `password/change` under `/api/auth/`, with serializers.
  Also enable `TokenAuthentication` here — deferred from task 00 per decision D9. Add
  `rest_framework.authtoken` to `INSTALLED_APPS` and append `TokenAuthentication` to the
  existing `DEFAULT_AUTHENTICATION_CLASSES` list in `config/settings/base.py`, which task 00
  deliberately left at `SessionAuthentication` only. Its migration declares an FK to
  `AUTH_USER_MODEL`, so it must land after 01.1, never before.
  **`ForcePasswordChangeMiddleware` cannot see token-authenticated requests** — DRF
  authenticates inside `APIView.initial()`, after middleware runs, so `request.user` is still
  `AnonymousUser` at that point for a token-bearing request. This task must add a DRF-side
  counterpart (a permission class, or a `DEFAULT_PERMISSION_CLASSES` entry) so a
  `must_change_password=True` user with a valid token doesn't get unrestricted API access (see
  design.md, "Temp password flow" step 3). Also add `POST /api/auth/password/change/` to the
  middleware's exempt-path list — by exact path, not an `/api/auth/` prefix — or a
  temp-password client has no reachable way to clear the condition.
  *Files:* `accounts/api.py`, `accounts/serializers.py`, `accounts/api_urls.py`,
  `config/settings/base.py`
  *Done when:* all four appear in `/api/docs/` and round-trip correctly, and a minted token
  authenticates an API request while `BasicAuthentication` remains disabled.

- [ ] **01.8 — Login throttling**
  `ScopedRateThrottle` at `5/min` on both login paths.
  *Files:* `config/settings/base.py`, `accounts/api.py`, `accounts/views.py`
  *Done when:* the sixth attempt in a minute returns 429.

  Carried over from the 01.6/01.7 review — resolve here:
  - **Size the throttle knowing a failed login costs ~239 ms of PBKDF2**, roughly double a
    success. `accounts/forms.py` deliberately runs a dummy `set_password()` on the
    `DoesNotExist` branch to equalise timing against user enumeration, so every failure pays
    the hashing cost. An attacker burns double CPU per attempt; so does the server.
  - **Nothing in CI guards that timing property.** `config/settings/test.py` uses
    `MD5PasswordHasher`, which masks the difference — a regression that reintroduced the
    2.2x enumeration oracle would not turn the suite red. If a guard is worth having, it
    needs a PBKDF2-pinned test.
  - **Tighten three assertions in `accounts/tests/test_services.py`** that would pass through
    a regression: the in-memory-consistency assertions that run *after* `refresh_from_db()`,
    which makes them tautological.

- [ ] **01.9 — Bootstrap superuser command**
  `manage.py bootstrap_admin` creating the first admin with a printed temp password, so a
  fresh deployment has a way in. Idempotent — refuses politely if an admin already exists.
  *Files:* `accounts/management/commands/bootstrap_admin.py`

  Carried over from the 01.6/01.7 review — resolve here:
  - **`set_temp_password` mutates the caller's `User` instance before its `transaction.atomic()`
    block and does not restore it if the write fails.** `complete_password_change` had the same
    flaw and now restores state in an `except`; `set_temp_password` was left as-is because
    nothing called it outside tests. **This command is its first real caller.** A caller that
    catches the exception and later calls `user.save()` would commit a half-applied reset —
    `must_change_password=True` paired with a temp password the admin was never shown, locking
    the account with no way in. Fix it here, or mirror the `except` restore.
  - **The restoration path does not clear `user._password`**, leaving a plaintext password on
    the in-memory object if the exception comes from `save()` itself. Harmless today (no
    configured validator implements `password_changed`), but it is why a hand-maintained
    field mirror is fragile — `user.refresh_from_db()` in the `except` would be consistent by
    construction.
  - **Test-plan "Manual verification" step 1 becomes performable once this lands** — log in
    with a generated temp password, confirm the forced-change screen appears and that no other
    page is reachable until it is done. It could not be done during 01.6/01.7 because there was
    no way to mint a temp password by hand; the flow is covered by automated tests meanwhile.

- [ ] **01.10 — Update the living document**
  Task 01 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
