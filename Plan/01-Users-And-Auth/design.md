# 01 — Users & Authentication · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)

## Goal

Admin-provisioned accounts, a temp-password flow that forces a reset on first login, and
sessions that survive closing the browser.

**Depends on:** 00-Foundations.
**Enables:** everything. No model can reference a user until the custom user model exists.

> **This task must land before any domain model is written.** Swapping in a custom user model
> after other tables have foreign keys to `auth.User` is one of the genuinely painful
> migrations in Django. It is cheap now and expensive in three tasks' time.

## The user model

`accounts.User(AbstractUser)` — subclassing `AbstractUser` rather than `AbstractBaseUser`
keeps the admin, permissions, and password machinery for free, which is the right trade for a
20-user app.

```python
class User(AbstractUser):
    must_change_password = models.BooleanField(default=False)
    temp_password_expires_at = models.DateTimeField(null=True, blank=True)
```

`AUTH_USER_MODEL = "accounts.User"` in `base.py`. Admin status uses Django's existing
`is_staff` / `is_superuser` rather than a new field — the requirement "entitle a user as an
admin" maps onto `is_staff`, and inventing a parallel flag would mean two sources of truth
about who is an admin.

**No self-registration.** There is no signup view, no signup URL, and no password-reset-by-
email flow. Accounts come from an admin (task 09). This is a requirement, and it also removes
the entire account-enumeration and email-deliverability surface.

## Temp password flow

1. An admin creates a user and the system generates a temp password — `secrets.token_urlsafe`,
   never anything guessable or derived from the username. It is displayed to the admin **once**
   and never stored in plain text.
2. The user is saved with `must_change_password=True` and
   `temp_password_expires_at = now + 7 days`.
3. On successful login with `must_change_password=True`, every request is redirected to
   `/accounts/password/change/` until it is done. Enforced by **middleware**, not by
   remembering to check in each view — a per-view check is a per-view chance to forget.

   **This does not extend to token-authenticated API requests.** DRF's `TokenAuthentication`
   (enabled in 01.7) authenticates inside `APIView.initial()`, which runs *after*
   `ForcePasswordChangeMiddleware`. At the point the middleware runs, `request.user` is still
   `AnonymousUser` for a token-bearing request, so it sails straight through and a
   `must_change_password=True` user with a valid token gets unrestricted API access. 01.7 needs
   a DRF-side counterpart — a permission class, or a `DEFAULT_PERMISSION_CLASSES` entry — to
   close this gap; middleware alone cannot reach it.
4. On a successful change, `set_password` alone invalidates every existing session for the
   user, including the one making the request: changing the stored hash also changes
   `User.get_session_auth_hash()`, so the next request's `django.contrib.auth.get_user()` fails
   `constant_time_compare` against the session's stored hash and calls
   `request.session.flush()`, deleting the session row outright. This is **stronger** than
   `update_session_auth_hash` — that call spares only the *current* session while killing
   others; a bare `set_password` kills all of them, the acting user's included. Because of
   that, **01.6's password-change view must call `update_session_auth_hash(request, user)`
   immediately after `complete_password_change`** — the service has no `request` to do this
   itself — or the forced-reset flow ends by flushing the very session that just completed it,
   bouncing the user back to the login screen instead of into the app.
5. An expired temp password refuses login with "This temporary password has expired. Ask an
   admin to issue a new one." — it does not silently work forever. This check does **not**
   belong in `LoginView`: Django's `authenticate()` succeeds against an expired temp password
   regardless of what a view does with the result, so anything else that calls `authenticate()`
   — `/admin/login/`, reachable today, and 01.7's API login — would still let it in. The choke point
   for *enforcement* is a `ModelBackend` subclass overriding `user_can_authenticate`, since
   every `authenticate()` call path already consults that method. It also gates
   `ModelBackend.get_user()`, so the override ends an expired user's already-open sessions,
   not just their new logins.

   **Enforcement and the message are separate layers, and the backend cannot carry both.**
   `user_can_authenticate` returning `False` makes `authenticate()` return `None`, and
   `AuthenticationForm.clean` answers `None` with the generic "Please enter a correct username
   and password" — `confirm_login_allowed()` never runs, since it only runs when
   `authenticate()` returned a user. Raising `PermissionDenied` in the backend does not help
   either; `authenticate()` swallows it and returns `None`. So 01.6 must supply the message
   from the form layer: an `AuthenticationForm` subclass that, on an invalid login, re-checks
   `user.check_password(password) and temp_password_expired(user)` and substitutes the expiry
   text. This is not the enumeration oracle "Edge cases" warns about — it is reachable only by
   someone who already has the correct password.

   The backend is **not** a choke point for DRF `TokenAuthentication` (01.7), which never calls
   `authenticate()`. There, expiry is covered only transitively: an expired temp password
   implies `must_change_password=True`, which the API's own guard must enforce.

   The rule itself belongs in `accounts/services.py`, per `CLAUDE.md` §3, as something like
   `temp_password_expired(user) -> bool`, not written inline in the backend or a view. Pin its semantics:
   `temp_password_expires_at is None` **with** `must_change_password=True` — reachable by an
   admin ticking `must_change_password` by hand in Django Admin without also setting an expiry
   — means "forced change, no deadline," not "expired."

### The middleware

`accounts.middleware.ForcePasswordChangeMiddleware`. Redirects authenticated users with
`must_change_password=True` to the change form. **Exempt paths:** the change form itself,
logout, `/healthz/`, static/media, and `POST /api/auth/password/change/` — without the first
group the redirect loops, and without the last one a temp-password API client gets `403
{"detail": "password_change_required"}` on every request, including the one request that would
clear the condition, leaving it no reachable way out. The API exemption must match the
**exact path** `/api/auth/password/change/`, not an `/api/auth/` prefix — a prefix match would
also exempt `/api/auth/me/` and every other authenticated endpoint from enforcement.

For API requests (`/api/`) it returns `403` with a machine-readable
`{"detail": "password_change_required"}` rather than a redirect, because a REST client cannot
follow a redirect to an HTML form.

## Sessions

```python
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365      # one year
SESSION_SAVE_EVERY_REQUEST = True             # rolling — active users never get logged out
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True                  # prod only
```

`SESSION_SAVE_EVERY_REQUEST` is what makes "stay logged in until you click logout" true rather
than "stay logged in for a year from your first login."

DRF `TokenAuthentication` is enabled alongside session auth for a future native client. It is
unused by the web UI, and no UI exists to mint tokens yet.

## Views and endpoints

**HTML** (`accounts/urls.py`)

| Route | View | Notes |
|---|---|---|
| `GET/POST /accounts/login/` | `LoginView` | Django's, with a project template. Throttled. |
| `POST /accounts/logout/` | `LogoutView` | POST only — a GET logout is CSRF-triggerable from an `<img>` tag. |
| `GET/POST /accounts/password/change/` | `PasswordChangeView` | Doubles as the forced-reset screen; the copy changes when `must_change_password` is set. |
| `GET /accounts/profile/` | `ProfileView` | Username, join date, change-password link. |

**API** (`/api/auth/`)

| Route | Notes |
|---|---|
| `POST /api/auth/login/` | Session login for API clients. Throttled at 5/min per IP. |
| `POST /api/auth/logout/` | |
| `GET /api/auth/me/` | Current user; includes `must_change_password`. |
| `POST /api/auth/password/change/` | |

## Login throttling

DRF `ScopedRateThrottle`, scope `login`, `5/min`. Applied to both the API login and — via a
small mixin — the HTML login view.

Accounts are admin-provisioned with no self-service recovery, so an attacker who locks out a
real user creates a support burden. Rate limiting is therefore keyed on IP and deliberately
**does not lock the account** — it slows the attacker without giving them a denial-of-service
lever against a legitimate user.

## Edge cases

- Login must not reveal whether a username exists. One message for both failures.
- Timing: Django's `authenticate()` already runs the hasher on a nonexistent user to equalise
  timing. Do not add an early `User.objects.filter(...).exists()` short-circuit — it would
  reintroduce the oracle.
- A user with `must_change_password=True` who logs out and back in is still forced to change.
- Deleting a user must not orphan their owned objects — deferred to task 03, which owns the
  `on_delete` policy. Note it here so it is not forgotten.
- Password validators: Django's four defaults, minimum length raised to 10.

## Security notes

- Passwords: Django's default PBKDF2, salted per user. Never log a password, never include one
  in an error message, never return one in a response.
- The generated temp password is returned exactly once, in the admin's create-user response.
  It is never persisted, never emailed, never retrievable afterward.
- Session cycling on password change is mandatory — otherwise a stolen session survives the
  very reset that was meant to end it.
- `LogoutView` is POST-only, and the login form is CSRF-protected by Django's middleware.
