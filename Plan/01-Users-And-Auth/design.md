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
   `authenticate()`. There, `PasswordChangeSerializer.validate_old_password` calls
   `temp_password_expired(user)` directly after the `check_password` check, so an expired temp
   password cannot be used as `old_password` to clear its own expiry — the one endpoint that
   remains reachable under a forced change does not double as a self-service escape hatch.

   The rule itself belongs in `accounts/services.py`, per `CLAUDE.md` §3, as something like
   `temp_password_expired(user) -> bool`, not written inline in the backend or a view. Pin its semantics:
   `temp_password_expires_at is None` **with** `must_change_password=True` — reachable by an
   admin ticking `must_change_password` by hand in Django Admin without also setting an expiry
   — means "forced change, no deadline," not "expired."

### The middleware

`accounts.middleware.ForcePasswordChangeMiddleware`. Redirects authenticated users with
`must_change_password=True` to the change form. **Exempt paths:** the change form itself,
`POST /accounts/logout/`, `/healthz/`, static/media, `POST /api/auth/password/change/`, and
`POST /api/auth/logout/` — without the first group the redirect loops, and without the API
password-change exemption a temp-password API client gets `403
{"detail": "password_change_required"}` on every request, including the one request that would
clear the condition, leaving it no reachable way out. Both API exemptions must match an
**exact path**, not an `/api/auth/` prefix — a prefix match would also exempt `/api/auth/me/`
and every other authenticated endpoint from enforcement.

The middleware runs before DRF's permission classes, so the API logout exemption has to live
here too, not only on `LogoutAPIView.permission_classes` — a permission-class-only fix closes
the gap for a token-authenticated client but leaves a session-authenticated one still 403'd by
the middleware before the permission is ever consulted.

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
unused by the web UI, and no *project* UI mints tokens.

> **Correction, iteration 3.** An earlier draft of this line said "no UI exists to mint tokens
> yet." That is false as shipped: adding `rest_framework.authtoken` to `INSTALLED_APPS`
> registers `authtoken.TokenProxy` in Django Admin, so `/admin/authtoken/tokenproxy/add/`
> mints a token for any user and returns 200 to a superuser. Blast radius is nil today — the
> default model permissions make it superuser-only, and the four `/api/auth/` endpoints give
> an impersonating token nothing a superuser does not already have — but it grows with every
> domain API added from task 04 onward. Task 09 decides whether to `admin.site.unregister`
> it or to keep it as a deliberate, audited admin action.

## Views and endpoints

**HTML** (`accounts/urls.py`)

| Route | View | Notes |
|---|---|---|
| `GET/POST /accounts/login/` | `LoginView` | Django's, with a project template. Throttled. |
| `POST /accounts/logout/` | `LogoutView` | POST only — a GET logout is CSRF-triggerable from an `<img>` tag. |
| `GET/POST /accounts/password/change/` | `PasswordChangeView` | Doubles as the forced-reset screen; the copy changes when `must_change_password` is set. `form_valid` is inherited, not overridden — Django's own implementation already calls `form.save()` then `update_session_auth_hash(request, form.user)`, exactly the ordering step 4 requires. |
| `GET /accounts/profile/` | `ProfileView` | Username, join date, change-password link. Also the interim target of `LOGIN_URL`/`LOGIN_REDIRECT_URL` below — task 02 has no home page yet. |

**API** (`/api/auth/`, `accounts/api_urls.py` — a separate module from the HTML routes above, mounted at a different prefix and sharing no views)

| Route | Notes |
|---|---|
| `POST /api/auth/login/` | Session login for API clients. `csrf_protect` applied directly (see "Security notes"). Throttled at 5/min per IP (01.8). |
| `POST /api/auth/logout/` | `permission_classes = [IsAuthenticated]`, overriding the project default so a forced-change user can still leave — also exempted in the middleware; see "The middleware". |
| `GET /api/auth/me/` | Current user; includes `must_change_password`. |
| `POST /api/auth/password/change/` | Rejects an expired temp password as `old_password` (see "Temp password flow" step 5). |

`config/settings/base.py` also sets, for this task: `AUTHENTICATION_BACKENDS =
["accounts.backends.TempPasswordAwareBackend"]`; `LOGIN_URL` and `LOGIN_REDIRECT_URL` pointing
at `accounts:profile` (interim — task 02 repoints these to a real home page);
`LOGOUT_REDIRECT_URL = "accounts:login"`; and `SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"]`
listing `IsAuthenticated` and `ForcePasswordChangeAPIPermission` — `/api/schema/` and
`/api/docs/` set `permission_classes` directly and so bypass `DEFAULT_PERMISSION_CLASSES`
entirely, requiring the same list to be repeated there.

## Login throttling

DRF `ScopedRateThrottle`, scope `login`, `5/min`. Applied to all three credential-accepting
login paths: the API login, the HTML login view (via a small mixin), and `/admin/login/`
(Django's own `AdminSite.login`, wrapped ahead of `admin.site.urls` in `config/urls.py` since
it shares neither of the other two's view code). All three share one throttle scope/bucket, so
an attacker cannot dodge the budget by switching endpoints — `/admin/login/` fronts the
`bootstrap_admin`-created superuser at the guessable default username `admin` and would
otherwise be the least-protected path to the most valuable account.

Accounts are admin-provisioned with no self-service recovery, so an attacker who locks out a
real user creates a support burden. Rate limiting is therefore keyed on IP and deliberately
**does not lock the account** — it slows the attacker without giving them a denial-of-service
lever against a legitimate user.

In production, keying on IP requires two more things to actually hold: `REST_FRAMEWORK["NUM_PROXIES"]`
must be set (`config/settings/prod.py`, not `base.py` — see that file's comment) so DRF trusts
only the hop Caddy itself appended to `X-Forwarded-For` rather than a client-supplied header
value verbatim; and the throttle's counters must live in a cache shared across gunicorn's
worker processes (`CACHES` in `prod.py`, `FileBasedCache` — `LocMemCache`, Django's unconfigured
default, is per-process and would silently multiply the enforced rate by the worker count).

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
- The generated temp password is never persisted and never emailed. It is never recoverable
  from the database: `secrets.token_urlsafe(16)` is hashed on the way in and the plaintext is
  cleared from `user._password` on every path, including both rollback paths.

  **It is not, however, "never retrievable afterward" — an earlier draft of this line said
  that and it is false for the bootstrapped first admin.** `manage.py bootstrap_admin` (01.9)
  prints the temp password to stdout, and in the deployed container stdout is the Docker
  json-file log, which `docker compose logs app` will replay until the container is recreated.
  This is deliberate and unavoidable: it is the only channel that exists before any admin can
  log in, and task 10's first-boot runbook (10.16, step 5) depends on it. The claim holds
  unchanged for task 09's admin create-user flow, which returns the password in an HTTP
  response and writes it nowhere. Task 10 (10.7) constrains the exposure window with log
  rotation.
- Session cycling on password change is mandatory — otherwise a stolen session survives the
  very reset that was meant to end it. `complete_password_change` also revokes every DRF
  `authtoken.Token` for the user in the same transaction, for the same reason: a token has no
  relationship to the password hash, so without this a leaked token would survive the reset
  meant to end it. `set_temp_password` (an admin re-issuing a temp password) revokes tokens
  too — every password-setting path is expected to route through a service that does this,
  so a future admin create/reset flow (task 09) inherits it rather than rediscovering it.
- `LogoutView` is POST-only. The HTML login form is CSRF-protected by Django's middleware;
  `POST /api/auth/login/` additionally applies `django.views.decorators.csrf.csrf_protect`
  directly, because DRF's `SessionAuthentication.enforce_csrf` only runs for a request that
  already carries an authenticated session — an anonymous API login POST would otherwise never
  be checked. One consequence: `csrf_protect` makes `POST /api/auth/login/` browser-only in
  practice (a bearer token has no CSRF exposure and is exempt), and with no token-minting
  endpoint yet, a headless/native client has no supported way to authenticate — the answer when
  that is needed is a token-minting endpoint, not loosening CSRF.
