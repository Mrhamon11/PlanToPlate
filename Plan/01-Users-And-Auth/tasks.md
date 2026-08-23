# 01 — Users & Authentication · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

- [ ] **01.1 — Custom user model**
  `accounts.User(AbstractUser)` with `must_change_password` and `temp_password_expires_at`.
  Set `AUTH_USER_MODEL`. Generate and read the initial migration before applying it.
  *Files:* `accounts/models.py`, `accounts/migrations/0001_initial.py`, `config/settings/base.py`
  *Done when:* `migrate` succeeds on a fresh database and `get_user_model()` returns `accounts.User`.

  > Do this before anything else in the project creates a user foreign key.

- [ ] **01.2 — Session configuration**
  The session settings block from the design, secure flags gated to prod.
  *Files:* `config/settings/base.py`, `config/settings/prod.py`
  *Done when:* the settings tests in the test plan pass.

- [ ] **01.3 — Password validators**
  Django's four defaults with `min_length=10`.
  *Files:* `config/settings/base.py`

- [ ] **01.4 — Temp password service**
  `accounts/services.py`: `generate_temp_password()`, `set_temp_password(user)`,
  `complete_password_change(user, new_password)`.
  *Files:* `accounts/services.py`
  *Done when:* generation uses `secrets`, and completion clears both fields inside one transaction.

- [ ] **01.5 — Forced password change middleware**
  `ForcePasswordChangeMiddleware` with the exempt-path list. HTML → redirect, `/api/` → 403 JSON.
  *Files:* `accounts/middleware.py`, `config/settings/base.py`
  *Done when:* no redirect loop, and the API branch returns JSON rather than HTML.

- [ ] **01.6 — HTML auth views and templates**
  Login, logout (POST only), password change, profile. Templates extend the base from task 02;
  until that lands, a minimal standalone template is acceptable and gets restyled there.
  *Files:* `accounts/views.py`, `accounts/urls.py`, `templates/accounts/*.html`
  *Done when:* the full login → forced change → app flow works in a browser.

- [ ] **01.7 — API auth endpoints**
  `login`, `logout`, `me`, `password/change` under `/api/auth/`, with serializers.
  Also enable `TokenAuthentication` here — deferred from task 00 per decision D9. Add
  `rest_framework.authtoken` to `INSTALLED_APPS` and append `TokenAuthentication` to the
  existing `DEFAULT_AUTHENTICATION_CLASSES` list in `config/settings/base.py`, which task 00
  deliberately left at `SessionAuthentication` only. Its migration declares an FK to
  `AUTH_USER_MODEL`, so it must land after 01.1, never before.
  *Files:* `accounts/api.py`, `accounts/serializers.py`, `accounts/urls.py`,
  `config/settings/base.py`
  *Done when:* all four appear in `/api/docs/` and round-trip correctly, and a minted token
  authenticates an API request while `BasicAuthentication` remains disabled.

- [ ] **01.8 — Login throttling**
  `ScopedRateThrottle` at `5/min` on both login paths.
  *Files:* `config/settings/base.py`, `accounts/api.py`, `accounts/views.py`
  *Done when:* the sixth attempt in a minute returns 429.

- [ ] **01.9 — Bootstrap superuser command**
  `manage.py bootstrap_admin` creating the first admin with a printed temp password, so a
  fresh deployment has a way in. Idempotent — refuses politely if an admin already exists.
  *Files:* `accounts/management/commands/bootstrap_admin.py`

- [ ] **01.10 — Update the living document**
  Task 01 → AWAITING APPROVAL.
  *Files:* `Plan/MILESTONES.md`
