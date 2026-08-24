# PlanToPlate — Living Project Document

> **Read this file at the start of every session. Update it at the end of every task.**
> It is the single source of truth for what this project is, how it is built, what has been
> decided, and what has been finished. If this file and your memory of a previous session
> disagree, this file wins.

---

## 1. What we are building

A self-hosted web app for storing recipes, composing them into meals, planning a week of
dinners, and generating the shopping list that follows from that plan.

**Scale:** 10–20 users, rarely concurrent. It runs on a machine in the owner's apartment,
reached over Tailscale or a reverse proxy. It is not a public SaaS and should not be
architected as one — but it must survive being moved to an EC2 instance or a VPS without a
rewrite.

**Author's context:** the owner is learning Django on this project and writes the code
alongside Claude. Prefer the idiomatic Django solution over the clever one, and prefer the
solution that teaches something over the one that hides everything behind a library.

Original requirements: [`../MarkdownFiles/PlanToPlate-Requirments.md`](../MarkdownFiles/PlanToPlate-Requirments.md)

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | Pinned in `.python-version`, matched by `requires-python = ">=3.13"`. One version across the venv, the lockfile and the container image. |
| Framework | Django 5.x (`>=5.1,<6`; 5.2.x in the lockfile) | 5.1 is the floor: SQLite's `OPTIONS["transaction_mode"]` arrived there, and the concurrency config depends on it. |
| API | Django REST Framework | Required for future native clients |
| Frontend | Django templates + HTMX + a little Alpine.js | No build step, no CORS, no duplicated auth. Server-rendered keeps the learning focused on Django. |
| Database | SQLite (WAL) | 10–20 users. Postgres-portable by rule, not by hope. |
| Dependencies | `uv` | Fast, lockfile-based, single tool |
| Tests | `pytest` + `pytest-django` + `factory_boy` + `coverage` | |
| Lint/format | `ruff` (both) | One tool, no config wars |
| API docs | `drf-spectacular` | OpenAPI schema + Swagger UI |
| Filtering | `django-filter` + DRF pagination | |
| Static files | `whitenoise` | No separate static server needed |
| Background jobs | `django-q2` | Only needed for the recipe extractor. SQLite-friendly; Celery+Redis is overkill here. |
| Images | `Pillow`, `MEDIA_ROOT` with a `django-storages` seam | |
| Serving | `gunicorn` (gthread) behind Caddy | Caddy does automatic TLS |
| Packaging | Docker Compose, with a plain systemd path documented as the alternative | Makes the EC2/VPS move a non-event |

### Development and deployment environments

**Development always runs in a virtual environment.** `uv` creates and manages `.venv`; you
never activate it by hand. Every command goes through `uv run`. **Never `pip install`** — a
package installed outside `uv` is missing from `uv.lock`, therefore missing from the container,
therefore a bug that only appears in production. Dependencies change via `uv add` / `uv remove`.

**Deployment is Docker Compose on a local server.** The venv and the image install the *same
dependency set* from the *same committed `uv.lock`*, which is what stops dev and prod drifting.

The container is designed to work from a cold start with no manual setup: `docker-entrypoint.sh`
runs `migrate` and `collectstatic` on every boot (both idempotent), and on first run only seeds
the catalog and creates an admin, printing its temp password to the logs once. The single
manual step is providing a `SECRET_KEY` in `.env` — see decision D5.

### Authentication

Django **session cookies** — `HttpOnly`, `SameSite=Lax`, `Secure` in production.
`SESSION_COOKIE_AGE` is one year with `SESSION_SAVE_EVERY_REQUEST = True`, which satisfies
"stay logged in until you click logout, even after closing the browser."

DRF authentication is **`SessionAuthentication` only** for now, set explicitly rather than left
to DRF's default — the default silently includes `BasicAuthentication`, which would accept
unthrottled credentials on every endpoint and bypass the login view entirely.

`TokenAuthentication` is planned for a future native app but is **not enabled yet**; it lands in
task 01 alongside the custom `User` model. See decision D9.

> **Why not JWT:** revocation and refresh rotation are real work, and storing tokens where
> JavaScript can read them trades a CSRF risk we already handle for an XSS risk we would not.
> For a same-origin server-rendered app with 20 users, sessions are both simpler and safer.

### SQLite concurrency

Every environment sets these connection options. Missing them is how you get
`database is locked` under two concurrent writers.

```python
"OPTIONS": {
    "init_command": (
        "PRAGMA journal_mode=WAL; "
        "PRAGMA synchronous=NORMAL; "
        "PRAGMA busy_timeout=5000; "
        "PRAGMA foreign_keys=ON;"
    ),
    "transaction_mode": "IMMEDIATE",
}
```

Rules that follow from SQLite:
- Keep write transactions short. Never hold one open across an HTTP call or a slow loop.
- Serve with **threads, not many processes** (`gunicorn --workers 2 --threads 4`).
- `transaction_mode="IMMEDIATE"` takes the write lock up front, which turns a mid-transaction
  deadlock into an honest wait governed by `busy_timeout`.

### Postgres portability rule

No raw SQL. No SQLite-only functions. No reliance on SQLite's loose typing. Database config
comes from a `DATABASE_URL` environment variable via `django-environ`, so switching engines is
one line in `.env` plus a migration run. Full-text search stays at `icontains` for now
precisely because the good options diverge between the two engines.

---

## 3. Project layout

```
plantoplate/
├── config/                  # settings/, urls.py, wsgi.py, asgi.py
│   └── settings/            # base.py, dev.py, prod.py, test.py
├── core/                    # OwnedModel, visible_to(), permissions, sharing + copy services
├── accounts/                # custom User, temp-password flow, auth views
├── catalog/                 # Tag, Unit, Ingredient, unit conversion
├── recipes/                 # Recipe, RecipeComponent, cycle guard, scale/flatten, RecipeStats
├── meals/                   # Dish, RecipeBook, DishStats
├── lists/                   # List, ListItem, shopping-list aggregation
├── planner/                 # MealPlanProfile, MealPlan, the seeded generator
├── templates/               # base.html, per-app template dirs, HTMX partials in _partials/
├── static/
└── manage.py
```

**Conventions**

- Business logic lives in `<app>/services.py`. Views and serializers are thin: parse, call a
  service, render. If a view has branching business rules in it, it is in the wrong place.
- Tests live in `<app>/tests/` split into `test_models.py`, `test_services.py`,
  `test_api.py`, `test_permissions.py`, `test_views.py`.
- HTMX partials are named `_partials/<thing>.html` and return fragments, never full pages.
- All quantities are `Decimal`. Never `float`. Money-style precision problems apply equally
  to a quarter teaspoon.
- Migrations are reviewed before running. Never auto-apply a migration you have not read.
- **One branch per task**, named `task/<task-folder-lowercased>` (`task/05-recipes`). Cut when
  the task starts, from the default branch, and kept for the task's whole life however many
  sessions it spans. Agents cut branches freely; only a human commits, pushes, or merges.

---

## 4. Data model

```
User(AbstractUser)
    must_change_password: bool
    temp_password_expires_at: datetime?

OwnedModel(abstract)                    # every user-creatable object inherits this
    owner            → User
    visibility       PRIVATE | SHARED | PUBLIC      (default PRIVATE)
    shared_with      M2M(User, related_name="shared_%(class)ss")
    notes            text                            (every object gets free-form notes)
    copied_from      → self, null                    (provenance)
    is_system        bool                            (seeded objects, read-only to all)
    created_at / updated_at

Tag(name, kind: CUISINE | PROTEIN | DIET | FREEFORM)
Unit(name, abbrev, dimension: MASS | VOLUME | COUNT, to_base_factor, is_system)

Ingredient(OwnedModel)
    name, default_unit → Unit, density_g_per_ml: Decimal?, is_staple: bool, tags M2M(Tag)

Recipe(OwnedModel)
    name, instructions
    yield_quantity: Decimal, yield_unit → Unit        # REQUIRED — sub-recipes cannot scale without it
    prep_minutes: int, cook_minutes: int
    role: PROTEIN | CARB | VEGETABLE | ONE_POT | SAUCE | DESSERT | OTHER
    tags M2M(Tag)

RecipeComponent
    recipe → Recipe, position
    ingredient → Ingredient?  XOR  sub_recipe → Recipe?    # DB CHECK: exactly one
    quantity: Decimal, unit → Unit, note

Dish(OwnedModel)          ── DishComponent(dish, recipe, position)
RecipeBook(OwnedModel)    ── RecipeBookEntry(book, recipe, section, position)

List(OwnedModel)
    kind: SHOPPING | MEAL_PLAN | MENU | GENERIC
ListItem
    list, position, is_checked
    text? / recipe? / dish? / ingredient?              # heterogeneous content
    quantity: Decimal?, unit → Unit?
    source: MANUAL | GENERATED
    generated_from → MealPlan?

MealPlanProfile(owner, name, <the eight gears, section 5>)
MealPlan(OwnedModel)
    start_date, days, profile → MealPlanProfile, seed: int, shopping_list → List
MealPlanEntry(plan, day_index, slot: BREAKFAST | LUNCH | DINNER, dish)

RecipeStats(user, recipe, rating 0–5, is_favorite, times_made, last_made_at)  # unique together
DishStats(user, dish, rating 0–5, is_favorite, times_made, last_made_at)      # unique together
```

### The visibility keystone

This is the most security-critical convention in the codebase. **One implementation, used
everywhere:**

```python
class OwnedQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(
            Q(owner=user)
            | Q(visibility=Visibility.PUBLIC)
            | Q(shared_with=user)
            | Q(is_system=True)
        ).distinct()
```

Every viewset's `get_queryset()` and every template view's query goes through it. Object-level
writes are gated by a single `IsOwnerOrReadOnly` permission class. Never hand-roll an
ownership filter in a view — a filter written twice is a filter that will diverge once.

**Sharing rules:**
- Objects are **private by default**.
- Only the **owner** may share. A user holding a read-only object cannot reshare it — sharing
  is an ownership right, not an access right.
- `PUBLIC` means "every authenticated user." There is no anonymous access anywhere.
- Sharing a container **cascades read-grants to its children**. Sharing a Dish grants read on
  its Recipes and their Ingredients and sub-recipes. Without this, a shared object arrives at
  the recipient broken.
- **Copy = deep snapshot.** Copying someone's Dish gives you your own Recipes, with
  `copied_from` recording where they came from. A copy that holds pointers into someone
  else's data is a copy that breaks when they hit delete.
- `is_system` objects (seeded ingredients and units) are readable by everyone and writable by
  no one through the API — only through fixtures and the admin.

---

## 5. The meal planner

### The eight gears

The requirements asked for flexibility *without* decision fatigue. This is the complete,
deliberately capped set of knobs. Anything not on this list is out of scope; adding a ninth
gear is a decision to record here, not a thing to slip in.

1. **`days`** (1–7) and **`slots`** — dinner only by default; lunch and breakfast optional.
2. **`dish_template`** — `BALANCED` (protein + carb + vegetable), `ONE_POT`, or `MIX`.
3. **`source_scope`** — my recipes / + shared with me / + public.
4. **`tag_limits`** — `{tag: max_per_week}`, e.g. `{"chicken": 1}`. This is the "chicken only
   one day a week" requirement.
5. **`excluded_tags` / `excluded_ingredients`** — hard exclusions. Allergies live here.
6. **`no_repeat_days`** — never suggest something cooked in the last N days
   (via `RecipeStats.last_made_at`).
7. **`min_rating`** and **`favorites_only` / `favorites_bias`**.
8. **`max_total_minutes`** — prep + cook budget per meal.

Profiles are saved and named, so a week's plan is two clicks rather than eight decisions.

### The algorithm

Seeded `random.Random(plan.seed)` → filter the candidate pool per slot → randomized greedy
selection with bounded backtracking → return `PlanResult(entries, unfilled, reasons)`.

Two properties matter more than sophistication:

- **Deterministic under a fixed seed.** Without this the planner cannot be tested at all, and
  an untestable generator in the heart of the app is how this project stalls.
- **Degrades honestly.** If the constraints cannot be satisfied it returns a partial plan and
  says *which* constraint starved it ("only 2 recipes tagged vegetable are available"). It
  never loops forever and never silently ignores a constraint the user set.

### Shopping list generation

`flatten(dish) → [(ingredient, quantity, unit)]`:

1. Walk `DishComponent → Recipe → RecipeComponent`, recursing into `sub_recipe`.
2. Scale each sub-recipe's components by `requested_quantity / sub_recipe.yield_quantity`,
   converting units within the dimension first. **This is why `yield_quantity` is mandatory.**
3. Guard against cycles and cap depth at 5.
4. Aggregate by `(ingredient, dimension)` in base units; convert cross-dimension only when
   `Ingredient.density_g_per_ml` is set, otherwise keep the lines separate rather than
   inventing a number.
5. Convert back to a human-friendly unit for display.
6. Optionally drop `is_staple` ingredients so the list is not 40% salt and oil.

**Regeneration is idempotent.** Regenerating a plan deletes only `source=GENERATED` items on
the target list and rebuilds them. Manually added items survive untouched. If no shopping list
exists, one named "Shopping List" is created.

---

## 6. Security posture

Django's ORM parameterises queries and its templates escape output, so SQL injection and
reflected XSS are largely handled by using the framework correctly. **The real exposure in
this app is elsewhere**, in roughly this order:

1. **IDOR / broken object-level authorization.** A sharing model with per-object permissions
   is exactly the shape of app that leaks data through a missing queryset filter. Mitigated by
   the single `visible_to()` convention and by dedicated permission tests on every endpoint.
2. **Visibility leaking through relations** — a private sub-recipe surfacing inside a shared
   parent's serialized output.
3. **File upload** (task N1) — content-type sniffing, decompression bombs, SVG-borne XSS,
   path traversal. Validate with Pillow, re-encode, never trust the filename.
4. **SSRF** (task N2) — the recipe extractor fetches a user-supplied URL *from a machine
   inside a home LAN*. Private, loopback, and link-local ranges must be blocked, redirects
   re-validated at every hop, with size and time caps. This is the single most dangerous
   feature in the backlog.
5. **Brute force on login** — DRF scoped throttle, since accounts are admin-provisioned and
   there is no self-service lockout recovery.
6. **Mass JSON import** (task 09) — object-count caps, schema validation, and it must never
   let an importer set `owner` to another user.
7. **Temp passwords** — single-use, expiring, forced change on first login, session cycled on
   password change.

Passwords use Django's default PBKDF2 hasher (salted per-user). Admins can reset a password to
a new temp value; admins can never see an existing one.

---

## 7. Task status

Statuses: `NOT STARTED` · `IN PROGRESS` · `AWAITING APPROVAL` · `COMPLETE` · `BLOCKED`

| # | Task | Status | Completed | Notes |
|---|---|---|---|---|
| 00 | [Foundations](00-Foundations/design.md) | COMPLETE | 2026-08-19 | All 15 subtasks done; pipeline converged (tester PASS, reviewer APPROVE) after 5 blocking findings raised and resolved. Committed Dockerfile verified with a real `--no-cache` build and a full clean-volume `docker compose up` on the dev host: app healthy, Caddy gated on it, HTTPS `/healthz/` 200, data survives `down`/`up`, graceful SIGTERM shutdown (exit 0), and no database/`.env`/host `.venv` in the image. `seed_catalog`/`bootstrap_admin` don't exist yet (tasks 04/01) — the entrypoint skips them and writes no marker, so each runs exactly once when it lands. |
| 01 | [Users & Auth](01-Users-And-Auth/design.md) | COMPLETE | 2026-08-24 | All 10 subtasks implemented and approved by the project owner, who committed and pushed the branch. Pipeline converged on iteration 3 plus one authorised narrow pass — tester PASS, correctness reviewer APPROVE, security reviewer APPROVE, zero blocking findings outstanding. 118 passed, ruff clean, `check --deploy` clean. Iteration 1 was rejected by both reviewers with 7 blocking findings, all reproduced by measurement: `POST /api/auth/login/` was CSRF-unprotected (D24); an expired temp password could clear its own expiry through the API change endpoint; a DRF token survived the password change meant to revoke it; and the login form's expiry-message branch had reintroduced user enumeration as a 2.2x timing oracle. Iteration 2's API-logout fix was then found half-done — the middleware runs before DRF permissions, so session clients were still 403'd. Iteration 3 closed three more: a `Caddyfile` `header_up` at site level (a parse error that would have crash-looped Caddy and left the site unreachable), `bootstrap_admin`'s deactivated-admin check failing in the exact case it was added for, and a tautological test that passed because `AbstractBaseUser.save()` clears `user._password` itself. A fourth narrow pass pinned two unpinned invariants (`_reset`'s transaction, the 7-day temp-password lifetime). **One Definition-of-Done item was signed off unperformed:** manual verification #2 (close the browser, reopen, still logged in). The mechanism is asserted by a test on the session cookie's `max-age` and `SESSION_EXPIRE_AT_BROWSER_CLOSE = False`, so the behaviour is pinned in code; only the browser step itself was skipped. Fourteen non-blocking findings were deliberately deferred into tasks 02, 09 and 10 — see D25–D29 and the subtask bodies there. Custom User model landed at 01.1, so domain models may reference `AUTH_USER_MODEL`. |
| 02 | [UI Shell](02-UI-Shell/design.md) | NOT STARTED | — | Base templates, responsive layout, HTMX conventions |
| 03 | [Ownership & Sharing](03-Ownership-And-Sharing/design.md) | NOT STARTED | — | The visibility keystone. Heaviest security tests. |
| 04 | [Units & Ingredients](04-Units-And-Ingredients/design.md) | NOT STARTED | — | Unit conversion, seed data |
| 05 | [Recipes](05-Recipes/design.md) | NOT STARTED | — | Cycle guard, scale/flatten service |
| 06 | [Dishes & RecipeBooks](06-Dishes-And-RecipeBooks/design.md) | NOT STARTED | — | |
| 07 | [Lists & Shopping](07-Lists-And-Shopping/design.md) | NOT STARTED | — | Generated vs manual provenance |
| 08 | [Meal Planner](08-Meal-Planner/design.md) | NOT STARTED | — | Seeded generator, idempotent regeneration |
| 09 | [Admin Control Center](09-Admin-Control-Center/design.md) | NOT STARTED | — | Django Admin + custom actions |
| 10 | [Security & Deployment](10-Security-And-Deployment/design.md) | NOT STARTED | — | Backups, TLS, prod checklist |
| N1 | [Images & Camera](N1-Images-And-Camera/design.md) | NOT STARTED | — | Nice to have |
| N2 | [Recipe Extractor](N2-Recipe-Extractor/design.md) | NOT STARTED | — | Nice to have. SSRF-critical. |
| N3 | [Social Feed](N3-Social-Feed/design.md) | NOT STARTED | — | Nice to have |
| N4 | [PWA & Polish](N4-PWA-And-Polish/design.md) | NOT STARTED | — | Nice to have |

**Dependency order:** 00 → 01 → 02 → 03 → 04 → 05 → {06, 07} → 08 → 09 → 10.
Nice-to-haves: N1 after 05 · N2 after 05 and N1 · N3 after N1 and 06 · N4 after 02 and 08.

Tasks 04–08 are each vertical slices: models, services, REST API, HTMX screens, and tests.
Every one of them ends with something you can click.

---

## 8. Decision log

Decisions made before implementation began, and the reasoning behind them. Append here rather
than rewriting; a decision that gets reversed should be struck through with a note on why.

### Confirmed with the project owner

| # | Decision | Rationale |
|---|---|---|
| D1 | Django templates + HTMX, not a SPA | No build step, no CORS, no duplicated auth or validation. Roughly half the work, and it keeps the learning on Django. The REST API is still built for future native clients. |
| D2 | Django Admin, customized — not a bespoke admin UI | "Browse all tables, CRUD any row, manage users" *is* Django Admin. Building it by hand is weeks of re-inventing, and every hand-rolled admin is a new home for authorization bugs. |
| D3 | Rating / favorite / times-made on per-user rows | The requirements say "how many times made **by the user**." As fields on a shared object, one global rating serves everyone and copying discards your history. |
| D4 | All 15 task plans written up front; MVP detailed, nice-to-haves lighter | The nice-to-have designs will shift once the MVP is real. |
| D5 | `SECRET_KEY` must be supplied in `.env`; it is never auto-generated | Auto-generating into the data volume hides a security-critical value where people forget to back it up, and silently rotating it logs everyone out with no explanation. One documented manual step (`make secret`) is the better trade. |
| D6 | Container entrypoint runs migrate/collectstatic every boot, seeds and bootstraps an admin on first run only | "Deploy and it works" requires more than a Dockerfile — without this, `docker compose up` yields a container with an empty database. Idempotent steps run always; one-time steps are volume-guarded. |
| D7 | Development in a `uv`-managed venv; the same `uv.lock` builds the image | Prevents the "works on my machine" class of bug structurally rather than by discipline. |
| D8 | One branch per task; agents may cut branches but never commit, push, or merge | Branch creation destroys nothing, so gating it only adds friction. Committing is where judgement is needed, so that stays with the human. Because agents never commit, a finished task must be committed and merged before the next one starts — otherwise the next branch inherits an uncommitted working tree. |
| D9 | `TokenAuthentication` deferred from task 00 to task 01; DRF is `SessionAuthentication` only until then | `rest_framework.authtoken`'s initial migration declares an FK to `AUTH_USER_MODEL`. Creating it against `auth.User` and then swapping in a custom user is the classic painful Django migration, and nothing consumes tokens until a native client exists. `DEFAULT_AUTHENTICATION_CLASSES` is written explicitly now so Token is appended in 01 rather than DRF's Basic default being inherited. |
| D10 | Python pinned to 3.13 exactly, not "3.12+" | `.python-version`, `requires-python` and the container base image all name one version, so the interpreter cannot drift between the venv, the lockfile and production. `uv` fetches it, so no system Python is involved. |
| D11 | `ruff` excludes `Plan/`, `.claude/` and `MarkdownFiles/` via `extend-exclude` | `ruff format` rewrites Python code fences *inside* Markdown, so a repo-wide format was silently reformatting the plan documents and a hook script. `extend-exclude` rather than `exclude` because the latter replaces ruff's own defaults, un-excluding `.venv` and `.git`. |
| D12 | `/api/schema/` and `/api/docs/` require authentication | drf-spectacular serves both to `AllowAny` by default, which would override the project's default-deny permission and publish the full API shape anonymously. Set to `IsAuthenticated` rather than `IsAdminUser` so a future native-client developer can still read the schema, consistent with "there is no anonymous access anywhere" (section 4). Practical effect until task 01 ships login: viewing the docs in a browser needs a `createsuperuser` and an `/admin/` session. |
| D13 | Python base image pinned by digest AND to a specific `uv` image/version, both fetched and recorded at build time | `python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1`; `uv` copied in from `ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1`. Both re-pullable and re-verifiable; a rebuild months from now reproduces the same layers rather than picking up whatever Debian/uv shipped that week. |
| D14 | Runtime image builds with `uv sync --frozen --no-dev --group prod`, not bare `--no-dev` | `gunicorn` lives in the `prod` dependency group (design.md's own dependency list). `--no-dev` alone excludes `dev` but does not include non-default groups — without `--group prod` the runtime image has no WSGI server. No new dependency was added; this only changes which already-declared group ships in the image. |
| D15 | Caddy's `SITE_ADDRESS` env var (default `localhost`) drives Caddy's automatic HTTPS directly — no `tls internal` directive, no separate HTTP redirect block | Caddy already treats non-public hostnames (`localhost`, bare IPs, `.local`) as ineligible for public ACME and silently switches to its own internal CA, auto-adding the HTTP→HTTPS redirect. Pointing `SITE_ADDRESS` at a real domain gets a publicly trusted Let's Encrypt cert instead, with zero other changes — this is the literal "swap DATABASE_URL and uncomment postgres" pattern applied to TLS. Verified live: `curl http://localhost/healthz/` returns a 308 to `https://`, and `curl -k https://localhost/healthz/` returns 200 with HSTS headers set. |
| D16 | `DATABASE_URL` for the SQLite path is supplied by `compose.yaml` (`${DATABASE_URL:-sqlite:////app/data/db.sqlite3}`), not baked into `.env.example` | `base.py`'s own default (`BASE_DIR/db.sqlite3`) is correct for local `uv run` but would land the container's database on the ephemeral writable layer if reused as-is — the named data volume is mounted at `/app/data`, not `/app`. Keeping the container-specific default in `compose.yaml` means `.env.example` stays identical for local dev and Docker, and the Postgres swap (design.md) is still just editing `DATABASE_URL` in `.env`. |
| D17 | `make secret` generates its own dollar-sign-free character set instead of calling Django's `get_random_secret_key()` | Found live: Docker Compose interpolates `$VAR`/`${VAR}` inside `.env` **values**, not just inside `compose.yaml` — a `$` landing in a pasted `SECRET_KEY` is silently stripped when the container starts (confirmed: a generated key containing `$pj` came out of `docker compose exec app env` with `$pj` removed, no error, just a warning easy to miss). Django's default charset includes `$`. `make secret` now draws from the same charset minus `$`, same length (50) and entropy. `.env.example` documents the general escaping rule (`$$`) for anything else a deployer types into `.env` by hand (e.g. a Postgres password). |
| D18 | The entrypoint's first-run block checks command existence via `django.core.management.get_commands()`, not by pattern-matching command output; **each first-run command gets its own on-disk marker** (`${DATA_DIR}/.ran-seed_catalog`, `${DATA_DIR}/.ran-bootstrap_admin`), written only after that command actually runs — not one shared marker for the whole block | `seed_catalog` (task 04) and `bootstrap_admin` (task 01) don't exist yet. Checking Django's own command registry is precise regardless of Django version wording and can't be confused by an unrelated error message; a command that genuinely exists and fails still aborts startup via `set -e`, since only the existence check is wrapped, not the actual run, and the marker is only touched on the line after a successful run. A single shared marker was tried first and found broken in iteration 1 review: it was written once both commands had been *attempted* (existing or not), so once `seed_catalog` landed in task 04 it would be silently skipped forever on any volume that had already booted once under task 00 — recovery would have required an operator to know to delete a dotfile inside a Docker volume. Per-command markers mean each command runs exactly once, whenever it eventually ships, with no such trap. Verified live (three-boot sequence against the same volume): boot 1 with neither command implemented logs `Skipping first-run command 'seed_catalog': management command not implemented yet.` for both and writes no marker; boot 2, with a working `seed_catalog` now present, logs `Running first-run command: seed_catalog` and writes `.ran-seed_catalog`; boot 3 against that same volume logs `First-run command 'seed_catalog' already recorded done — skipping.` and does not run it again. A first-run command that exists and fails still exits non-zero, prints its traceback, and leaves no marker. |
| D19 | `psycopg[binary]` added as an **optional `postgres` dependency group** (`uv add --group postgres "psycopg[binary]"`), not a main dependency — approved by the project owner in `Plan/00-Foundations/.review-findings.md` after iteration 1 found the portability DoD item unsatisfiable with no driver in `uv.lock` at all | A main dependency would install the Postgres driver on every deployment, including the SQLite-only default this project is sized for (10–20 users, one box). An optional group, mirroring how `dev` and `prod` already work in this same `pyproject.toml`, keeps `uv sync`'s default behavior driver-free — confirmed live: a bare `uv sync` after `uv add --group postgres` immediately uninstalls `psycopg`/`psycopg-binary` (and `gunicorn`, the other non-default group) from `.venv`. The Docker image mirrors this with a build arg, `INCLUDE_POSTGRES` (default `false`), threaded into the `uv sync --group prod [--group postgres]` lines in `Dockerfile` and exposed via `compose.yaml`'s `app.build.args`; a default `docker compose build` produces an image with no `psycopg` importable, confirmed by `python -c "import psycopg"` failing in that image and succeeding only in one built with `--build-arg INCLUDE_POSTGRES=true`. Manual Verification #8 was then performed for real (not `uv run --with`, which iteration 1 used and which deliberately never touches the lockfile): `uv sync --group postgres` installed the driver from `uv.lock`, `DATABASE_URL` was pointed at a scratch Postgres container, `manage.py migrate` applied all migrations, and a read of `settings.DATABASES["default"]` confirmed `ENGINE` resolved to `django.db.backends.postgresql` with `OPTIONS: {}` — no SQLite pragmas attached. The commented-out `postgres` service in `compose.yaml` was also uncommented and brought up for real (rootless podman, Docker daemon unreachable in this environment — see task 00's tester note): the app container's entrypoint ran `migrate` against that live Postgres container, `django_migrations` and the rest of the schema landed in it (verified via `psql -c '\dt'`), and `/healthz/` returned `200 {"status": "ok", "database": "ok"}`, both via the container's own healthcheck and a direct request. Caddy could not be started in the same run only because rootless podman refuses to bind privileged ports 80/443 in this sandbox — an environment limitation, not a defect in the compose file; the app-to-Postgres path itself was fully exercised. Both the scratch Postgres container/volume and the `postgres`-tagged verification images were removed afterward, and `compose.yaml`'s `postgres` service block was restored to its exact prior commented form (only the surrounding documentation comment and the new `app.build.args` block are permanent, since they are needed for the switch to be accurate now that a build-time choice exists). `README.md` "Switching to Postgres" and `.env.example` now document `INCLUDE_POSTGRES` as the step the driver-less default was previously missing. |
| D20 | `config/settings/prod.py`'s `ALLOWED_HOSTS` always appends `"127.0.0.1"` on top of the operator-supplied value (`env.list("ALLOWED_HOSTS") + ["127.0.0.1"]`), rather than requiring `127.0.0.1` to be listed by hand or changing the healthcheck probe's `Host` header — approved by the project owner in `Plan/00-Foundations/.review-findings.md` (BLOCKING 5, reviewer Stage 3) | The Compose healthcheck hits gunicorn directly at `http://127.0.0.1:8000/healthz/`, carrying `Host: 127.0.0.1`. `README.md`'s own TLS instructions invite a deployer to set `ALLOWED_HOSTS` to a real public domain the moment they move off `localhost` — the single most common post-`localhost` edit — which would otherwise make the healthcheck 400, `app` never report healthy, and caddy's `depends_on: {app: {condition: service_healthy}}` mean the whole stack is never served: a silent, total outage one keystroke away, and effectively undiagnosable without the logging fix in D21 alongside it. Appending in settings rather than editing the probe's `Host` header (the alternative fix) keeps `compose.yaml` simpler and needs no per-deployment configuration; the residual exposure — a request arriving with `Host: 127.0.0.1` — is not reachable from outside, since the app port is unpublished and Caddy only matches `{$SITE_ADDRESS}`. Confirmed not to introduce any `check --deploy` warning. A regression test (`core/tests/test_views.py::test_healthz_reachable_by_compose_healthcheck_under_real_domain_allowed_hosts`) imports `config.settings.prod` fresh under a domain-only `ALLOWED_HOSTS` and asserts `/healthz/` answers 200 to `Host: 127.0.0.1` — mutation-checked live by deleting `+ ["127.0.0.1"]` from `prod.py` (test failed: `assert 400 == 200`, `DisallowedHost`) and restoring the file byte-for-byte. `.env.example` and `README.md`'s TLS section now state the constraint at the point `ALLOWED_HOSTS` is configured. |
| D21 | Added a `LOGGING` override in `config/settings/prod.py` only (not `base.py`), sending the `django` and `django.request` loggers to stderr at `INFO`/`ERROR` — approved by the project owner alongside D20 | With `DEBUG=False` and no override, Django's `DEFAULT_LOGGING` gates its console handler on `require_debug_true` and otherwise routes errors to `mail_admins`, which needs `ADMINS`/email this project has neither of — unhandled 500 tracebacks were being discarded entirely, with only a bare gunicorn access-log line (`"GET ... HTTP/1.1" 500`) visible in `docker compose logs`, on a deployment whose only telemetry *is* container logs. Scoped to `prod.py` rather than `base.py` so it cannot change pytest's log capture or `dev.py`'s `runserver` console experience, neither of which import it. `django.request` is set `propagate: False` so its `ERROR`-level records aren't also emitted a second time through the `django` logger's `INFO` handler. |
| D22 | A synchronised system clock is a documented build prerequisite, recorded in `README.md`; the image build is **not** to be made tolerant of clock skew | Task 00's image build failed for most of its development with `E: Release file ... is not valid yet`, which reads like a Debian mirror problem and is not one. The dev host's clock was running ~6h behind real time, so correctly-signed apt metadata appeared future-dated. An agent worked around it by adding `-o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false` to the runtime stage's `apt-get`, which reached the committed Dockerfile and silently disabled the check that protects against stale or replayed repository metadata — the mechanism a downgrade attack to known-vulnerable packages relies on. The flags were removed and the real fix (`chronyc makestep`) applied instead. Future sessions: the mirror-image symptom `Release file ... is expired` means the clock runs *ahead*. Diagnose with `timedatectl`; never re-add the flags. |
| D23 | `accounts.services.complete_password_change` does **not** call `update_session_auth_hash`, despite `Plan/01-Users-And-Auth/design.md` originally naming it as the session-cycling mechanism — the service invalidates sessions via `set_password` alone, and the `update_session_auth_hash(request, user)` call is an obligation on **01.6's view layer**, not on the service | A service function has no `request`, so it cannot call `update_session_auth_hash` — that function's whole job is to re-stamp `request.session` with the new auth hash. What the service does instead is sufficient and, against the threat the design cares about, strictly stronger: `set_password` changes `User.get_session_auth_hash()`, so on the next request `django.contrib.auth.get_user()` fails its `constant_time_compare` and calls `request.session.flush()` — the session **row is deleted**, not merely ignored, and it fails closed if `_auth_user_hash` is absent entirely. Verified live during task 01's review: pre-change `session_key` is a real key, post-change `client.session.session_key is None` and `get_user(client).is_anonymous is True`. The difference from the design's named mechanism is scope, not strength: `update_session_auth_hash` kills *other* sessions while deliberately sparing the current one, whereas `set_password` alone kills *every* session including the acting user's. So the security property in `design.md` ("a stolen session dies at the very reset that was meant to end it") holds without it. **The cost is usability, and it lands on 01.6:** a user completing their own forced password change is logged out by it unless the view calls `update_session_auth_hash(request, user)` immediately afterward — otherwise the forced-reset flow ends by bouncing them to a login screen they have no reason to expect. Recorded here because the deviation is deliberate and correct: a future session reading `design.md` against `services.py` would otherwise see a missing call and "fix" it by pushing `request` into the service layer, violating `CLAUDE.md` §3's rule that business logic lives in `services.py` — a service that needs a `request` is a view in disguise. `design.md`'s temp-password-flow step on session cycling, and 01.6's entry in `tasks.md`, were corrected in the same pass. |
| D24 | `POST /api/auth/login/` applies `django.views.decorators.csrf.csrf_protect` directly, which makes it **browser-only in production** — confirmed with the project owner on 2026-08-23, who stated there will never be a headless client | DRF's `SessionAuthentication.enforce_csrf()` only runs for a request that already carries an authenticated session, and `APIView.as_view()` is `csrf_exempt`, so an anonymous login POST was never CSRF-checked at all — measured during task 01's review at **200** with `APIClient(enforce_csrf_checks=True)` versus **403** for the HTML login. The attack it enabled is login CSRF: an attacker auto-submits *their own* credentials cross-site, `SameSite=Lax` does not block the `Set-Cookie`, and the victim then files recipes and shopping lists into the attacker's account. The fix's cost is that under HTTPS, Django's CSRF check also demands a same-origin `Origin`/`Referer` header; with `CSRF_TRUSTED_ORIGINS` unset in prod and no token-minting endpoint in the project, a native or headless client has no supported way to authenticate — measured 403 without a `Referer` even with a valid CSRF token and cookie. **Accepted deliberately.** If that ever changes, the answer is to add a token-minting endpoint (`TokenAuthentication` is already enabled and its `authtoken` tables already migrated), **not** to loosen or remove `csrf_protect` here. Recorded so a future session meeting a 403 on this endpoint does not read it as a bug and "fix" it by reopening the hole. |
| D25 | Login throttling is one `ScopedRateThrottle` bucket (`5/min`, scope `login`) shared by all three credential-accepting paths — `POST /api/auth/login/`, the HTML login view, and `/admin/login/` — and it **never locks an account** | Accounts are admin-provisioned with no self-service recovery, so a throttle that locked accounts would hand an attacker a free denial-of-service lever against the one admin who can undo it. One shared bucket means an attacker cannot multiply their budget by rotating endpoints (pinned by `test_all_three_login_endpoints_share_one_throttle_budget`). `/admin/login/` is covered by wrapping Django's admin login view and wiring it ahead of `admin.site.urls` in `config/urls.py`; DRF's throttling internals are reused against a plain `HttpRequest` for the two Django-rendered paths, and those two return a plain-text 429 (a styled page is deferred to 02.11). In production the throttle depends on two settings that live in `prod.py` only: `NUM_PROXIES = 1`, without which every request behind Caddy keys on Caddy's own IP, and a `FileBasedCache`, without which each gunicorn worker keeps its own `LocMemCache` counter and the effective rate is 5/min *per worker*. **Known degradation, deferred to 10.5:** `ScopedRateThrottle.get_cache_key` keys on `request.user.pk` when the request is authenticated and falls back to IP only when anonymous, so an attacker who already holds one valid account gets a second full budget from the same IP. Measured, not inferred. The design's stated invariant still holds; the prose calling this "per-IP" does not. |
| D26 | `manage.py bootstrap_admin` gained a `--force` flag that reactivates, promotes, and re-issues a temp password for whichever account already holds the target username | The plain run's idempotence probe was tightened to require `is_active=True`, because a *deactivated* superuser previously counted as "an admin already exists" and the command would skip — leaving a deployment with no usable admin and no way in. But tightening the probe without an escape hatch just moves the lockout: the deactivated admin still holds the username, so the re-run hits the UNIQUE constraint. `--force` is that hatch. The grant and the password write share one `transaction.atomic()`, so there is no path where an account is promoted but nobody holds its password (mutation-proven: deleting the `atomic()` turns `test_bootstrap_admin_force_rolls_back_the_grants_when_the_reset_fails` red). It is not a privilege-escalation surface in practice — its only invocation sites are the entrypoint, which passes no arguments, and a manual `docker compose exec`, so an invoker already has a shell that is root-equivalent for this app. **Two consequences deferred:** `--force` is a second entitlement-granting path that task 09 owns and must reconcile with its last-admin guard and audit trail (09.8, 09.13); and the tightened probe turned the deactivated-admin case from a graceful exit-0 skip into a `CommandError`, which under the entrypoint's `set -euo pipefail` crash-loops the container if `.ran-bootstrap_admin` is ever absent while an unusable `admin` exists — a database-only restore, the Postgres switch, or a deleted marker (10.7). |
| D27 | The bootstrapped first admin's temp password **is** retrievable after the fact, from `docker compose logs app`, and `Plan/01-Users-And-Auth/design.md` was corrected to say so | That design.md's Security notes claimed the temp password is "never persisted, never emailed, never retrievable afterward." The first two remain true everywhere; the third was never true for the bootstrap path and cannot be, because stdout is the only channel that exists before any admin can log in — and task 10's first-boot runbook (10.16, step 5) explicitly instructs the operator to read it from the container logs. `compose.yaml` sets no `logging:` options, so Docker's json-file driver keeps it until the container is recreated. Recorded rather than quietly fixed because the false sentence would otherwise have been inherited as a security guarantee by task 09, which builds the admin create-user flow where the claim *does* hold (the password is returned in an HTTP response and written nowhere). Log rotation to bound the window is deferred to 10.7. |
| D28 | Caddy **replaces** an untrusted client's `X-Forwarded-For` rather than appending to it, so `NUM_PROXIES = 1` is the load-bearing control and the `header_up X-Forwarded-For {remote_host}` line in the `Caddyfile` is belt-and-braces | Verified at runtime against the pinned `caddy:2.10.2-alpine`, not read off the docs: the shipped Caddyfile produces byte-identical upstream headers with and without the `header_up` line. The comments in `Caddyfile` and `config/settings/prod.py` assert the opposite (that Caddy appends) and are wrong; correcting them is deferred to 10.8, along with the reason it matters — `header_up X-Forwarded-For {remote_host}` becomes actively *harmful* the day a `trusted_proxies` global option is added (e.g. fronting with Cloudflare), because it would overwrite the real client IP with the upstream load balancer's and collapse every client into a single throttle bucket. Also recorded: `config/tests/test_caddyfile.py` asserts only that *some* `header_up` sits inside *some* `reverse_proxy`, and two production-broken Caddyfiles pass both it and `caddy validate` — one of them a complete throttle bypass. Strengthening that test is 10.8's job. |
| D29 | Adding `rest_framework.authtoken` to `INSTALLED_APPS` also registers `authtoken.TokenProxy` in Django Admin, so `/admin/authtoken/tokenproxy/add/` mints a token for any user | Found by measurement (`admin.site._registry` contains `authtoken.tokenproxy`; the add page returns 200 to a superuser), and it falsifies design.md's "no UI exists to mint tokens yet," which has been corrected in place. Blast radius today is nil — default model permissions make it superuser-only, and the four `/api/auth/` endpoints give an impersonating token nothing a superuser does not already have — but it grows with every domain API from task 04 onward, and D24 deliberately left token-minting as the *sanctioned* future answer for headless clients. Task 09 decides: `admin.site.unregister(TokenProxy)`, or keep it as a deliberate, audited admin action. Recorded so the next session does not inherit the false statement. |

### Corrections to the original requirements

Each of these is a hole found in `PlanToPlate-Requirments.md` during planning.

| # | Problem in the requirements | Resolution |
|---|---|---|
| C1 | Recipes may contain recipes, but `Recipe` had no yield — so a sub-recipe cannot be scaled | `yield_quantity` + `yield_unit` are required fields. "1 cup of marinara" is meaningless unless the marinara recipe declares it makes 4 cups. |
| C2 | Nothing prevented a recipe cycle (A → B → A) | Cycle detection on save, max depth 5, enforced in `recipes/services.py` on every write path. |
| C3 | "Many kinds of units" was undefined | `Unit(dimension, to_base_factor)`. Conversion within a dimension always; across dimensions only when the ingredient declares a density. Quantities are `Decimal`. |
| C4 | Rating/favorite/times-made could not live on the object once objects are shared | Per-user `RecipeStats` / `DishStats`. (Same as D3.) |
| C5 | Transitive visibility was undefined — sharing a Dish containing a private Recipe | Sharing cascades read-grants to referenced children; the share is refused if a child cannot be granted. |
| C6 | Copy semantics were undefined — reference or snapshot? | Deep snapshot with a `copied_from` provenance pointer. A copy that the original owner can delete out from under you is not a copy. |
| C7 | The planner had no way to distinguish a Protein from a Carb | Explicit `Recipe.role` field plus a `Tag` model. Deriving the role from ingredients is fragile and fails on exactly the interesting cases. |
| C8 | Regenerating a meal plan would duplicate every shopping-list item | `ListItem.source` = MANUAL or GENERATED. Regeneration replaces GENERATED only. |
| C9 | A random planner is an untestable planner | `MealPlan.seed` and a seeded RNG. Partial results carry reasons instead of looping. |
| C10 | The stated security concerns (SQLi, password hashing) are the ones Django already handles | Real risks documented in section 6: IDOR first, then upload handling and SSRF. Each gets dedicated tests. |
| C11 | "Deploy an AI agent to crawl the site" for recipe extraction | Parse `schema.org/Recipe` JSON-LD first — most recipe sites publish it, and it is exact and free. LLM only as fallback. |
| C12 | Stack gaps: no dependency manager, test framework, linter, API docs, background jobs, or **backups** | Filled in section 2. A recipe database with no backup story is one dead disk away from gone. |

### Open questions

- Whether `MealPlan` should also be renderable as a `List` of kind `MEAL_PLAN`, or stay a
  distinct model that merely *generates* a list. Currently distinct — revisit in task 08.
- Whether user-created Ingredients should be promotable to `is_system` by an admin, to stop
  fifteen users creating fifteen "Chicken Breast" rows. Deferred to task 09.

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **Recipe** | Ingredients + quantities + instructions + a yield. May contain other Recipes. |
| **Dish** | A collection of Recipes that make one complete meal. |
| **RecipeBook** | A user-organized collection of Recipes, with sections and ordering. |
| **List** | A heterogeneous ordered list of free text, Recipes, Dishes, or Ingredients. |
| **Meal Plan** | Dishes assigned to day/slot pairs for a week, generated or hand-picked. |
| **Component** | A single line of a Recipe — either an Ingredient or a sub-Recipe, with a quantity. |
| **Dimension** | The physical kind of a unit: MASS, VOLUME, or COUNT. |
| **Staple** | A pantry ingredient (salt, oil, pepper) omitted from generated shopping lists. |
| **System object** | A seeded, globally readable, nobody-writable object (`is_system=True`). |
| **Flatten** | Recursively expand a Dish or Recipe into a scaled, aggregated ingredient list. |

---

## 10. Session checklist

**Starting:** read this file → read the task's `design.md`, `tasks.md`, `test-plan.md` →
confirm prerequisite tasks are COMPLETE → `uv sync && uv run pytest` to confirm you start green.

**Finishing:** full suite green → `ruff` clean → every Definition of Done item in the task's
`test-plan.md` satisfied → subtasks ticked in `tasks.md` → **this file updated** (status table,
and the decision log if anything was settled) → ask before committing.
