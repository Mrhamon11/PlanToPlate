# PlanToPlate — Architecture & Decisions

> Stable reference for every implementation and review agent: the stack, the layout, the data
> model, the security posture, and every binding decision. Read this before writing or
> reviewing code. Task **status** and the per-task change log live in `MILESTONES.md`, not here.
> If this file and your memory of a previous session disagree, this file wins.

---

## 1. What we are building

A self-hosted web app for storing recipes, composing them into meals, planning a week of
dinners, and generating the shopping list that follows.

**Scale:** 10–20 users, rarely concurrent, on a machine in the owner's apartment reached over
Tailscale or a reverse proxy. Not a public SaaS — but it must survive a move to an EC2
instance or VPS without a rewrite.

**Author's context:** the owner is learning Django and writes the code alongside Claude.
Prefer the idiomatic Django solution over the clever one, and the one that teaches something
over the one that hides everything behind a library.

Original requirements: [`../MarkdownFiles/PlanToPlate-Requirments.md`](../MarkdownFiles/PlanToPlate-Requirments.md)

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.13 (pinned exactly — `.python-version`, `requires-python`, container base all name one version) |
| Framework | Django 5.x (`>=5.1,<6`; 5.2.x in the lock). 5.1 floor: SQLite `OPTIONS["transaction_mode"]` |
| API | Django REST Framework |
| Frontend | Django templates + HTMX + a little Alpine.js. No build step, no SPA. |
| Database | SQLite (WAL). Postgres-portable by rule. |
| Dependencies | `uv` (lockfile-based) |
| Tests | `pytest` + `pytest-django` + `factory_boy` + `coverage` |
| Lint/format | `ruff` (check + format) |
| API docs | `drf-spectacular` |
| Filtering | `django-filter` + DRF pagination |
| Static | `whitenoise` |
| Background jobs | `django-q2` (only for the recipe extractor, N2) |
| Images | `Pillow`, `MEDIA_ROOT` with a `django-storages` seam |
| Serving | `gunicorn` (gthread) behind Caddy (automatic TLS) |
| Packaging | Docker Compose; plain systemd documented as the alternative |

### Environments

**Development always runs in a `uv`-managed venv.** Never activate by hand, never `pip
install`, every command through `uv run`. Dependencies change via `uv add` / `uv remove`
(needs permission). **Deployment is Docker Compose**; the venv and the image install the same
dependency set from the same committed `uv.lock`.

The container works from a cold start: `docker-entrypoint.sh` runs `migrate` and
`collectstatic` every boot (idempotent) and, on first run only, seeds the catalog and creates
an admin (temp password printed to logs once). The one manual step is supplying `SECRET_KEY`
in `.env` (D5).

### Authentication

Django **session cookies** — `HttpOnly`, `SameSite=Lax`, `Secure` in prod. `SESSION_COOKIE_AGE`
one year with `SESSION_SAVE_EVERY_REQUEST = True` ("stay logged in until you click logout").

DRF authentication is **`SessionAuthentication` + `TokenAuthentication`**, set explicitly (DRF's
default silently includes `BasicAuthentication`). No JWT: for a same-origin server-rendered app
with 20 users, sessions are simpler and safer. Token auth is enabled for a future native client;
nothing mints tokens through the UI yet (see D24, D29).

### SQLite concurrency

Every environment sets these connection options — missing them is how you get `database is
locked` under two writers:

```python
"OPTIONS": {
    "init_command": (
        "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; "
        "PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;"
    ),
    "transaction_mode": "IMMEDIATE",
}
```

Rules that follow: keep write transactions short (never across an HTTP call or slow loop);
serve with threads not many processes (`gunicorn --workers 2 --threads 4`);
`transaction_mode="IMMEDIATE"` turns a mid-transaction deadlock into an honest `busy_timeout`
wait.

### Postgres portability

No raw SQL, no SQLite-only functions, no reliance on loose typing. DB config comes from a
`DATABASE_URL` env var via `django-environ`. Full-text search stays at `icontains` for now.

---

## 3. Project layout

```
plantoplate/
├── config/                  # settings/{base,dev,prod,test}.py, urls.py, wsgi.py, asgi.py
├── core/                    # OwnedModel, visible_to(), permissions, sharing + copy services
├── accounts/                # custom User, temp-password flow, auth views
├── catalog/                 # Tag, Unit, Ingredient, unit conversion
├── recipes/                 # Recipe, RecipeComponent, cycle guard, scale/flatten, RecipeStats
├── meals/                   # Dish, RecipeBook, DishStats
├── lists/                   # List, ListItem, shopping-list aggregation
├── planner/                 # MealPlanProfile, MealPlan, the seeded generator
├── templates/               # base.html, per-app dirs, HTMX partials in _partials/
├── static/
└── manage.py
```

**Conventions**

- Business logic lives in `<app>/services.py`. Views and serializers are thin: parse, call a
  service, render. Branching business rules in a view means it is in the wrong place.
- Tests live in `<app>/tests/` split into `test_models.py`, `test_services.py`, `test_api.py`,
  `test_permissions.py`, `test_views.py`.
- HTMX partials are named `_partials/<thing>.html` and return fragments, never full pages.
- All quantities are `Decimal`, never `float`.
- Migrations are read before they are run.
- **One branch per task**, `task/<task-folder-lowercased>`, cut once from the default branch and
  kept for the task's whole life. Agents cut branches freely; only a human commits, pushes,
  merges (D8).
- `ruff` excludes `Plan/`, `.claude/`, `MarkdownFiles/` via `extend-exclude` — it reformats
  Python code fences inside Markdown, so never expect it to touch those trees (D11).

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
    notes            text
    copied_from      → self, null                    (provenance)
    is_system        bool                            (seeded objects, read-only to all)
    contains_owned_children: bool | None            (explicit opt-out for leaf models, D33)
    created_at / updated_at

Tag(name, kind: CUISINE | PROTEIN | DIET | FREEFORM)
Unit(name, abbrev, dimension: MASS | VOLUME | COUNT, to_base_factor, count_family, is_system)

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
    text? / recipe? / dish? / ingredient?
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

### The visibility keystone — the most security-critical convention in the codebase

**One implementation, used everywhere:**

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

Every viewset's `get_queryset()` and every template view's query goes through `.visible_to(user)`.
Object-level writes are gated by the single `IsOwnerOrReadOnly` permission class. Never
hand-roll an ownership filter in a view.

**Sharing rules:**

- Private by default. Only the **owner** may share — a read-only holder cannot reshare.
- `PUBLIC` means "every authenticated user." No anonymous access anywhere.
- Sharing a container **cascades read-grants to its children** (sharing a Dish grants read on
  its Recipes, their Ingredients, and sub-recipes). The share is refused if a child cannot be
  granted. Unsharing does **not** cascade back (D31).
- **Copy = deep snapshot.** Copying a Dish gives you your own Recipes, with `copied_from`
  recording provenance. No pointers into someone else's data.
- `is_system` objects are readable by everyone, writable by no one through the API — only
  fixtures and the admin.

---

## 5. The meal planner

### The eight gears — the complete, deliberately capped knob set

Adding a ninth is a decision to record, not a thing to slip in.

1. **`days`** (1–7) and **`slots`** — dinner only by default; lunch/breakfast optional.
2. **`dish_template`** — `BALANCED` (protein + carb + vegetable), `ONE_POT`, or `MIX`.
3. **`source_scope`** — my recipes / + shared with me / + public.
4. **`tag_limits`** — `{tag: max_per_week}`, e.g. `{"chicken": 1}`.
5. **`excluded_tags` / `excluded_ingredients`** — hard exclusions. Allergies live here.
6. **`no_repeat_days`** — never suggest something cooked in the last N days (`RecipeStats.last_made_at`).
7. **`min_rating`** and **`favorites_only` / `favorites_bias`**.
8. **`max_total_minutes`** — prep + cook budget per meal.

Profiles are saved and named.

### The algorithm

Seeded `random.Random(plan.seed)` → filter the candidate pool per slot → randomized greedy
selection with bounded backtracking → return `PlanResult(entries, unfilled, reasons)`.

- **Deterministic under a fixed seed** — without this the planner is untestable.
- **Degrades honestly** — if constraints cannot be satisfied it returns a partial plan and
  names the starving constraint ("only 2 recipes tagged vegetable are available"). Never loops
  forever, never silently ignores a constraint.

### Shopping list generation — `flatten(dish) → [(ingredient, quantity, unit)]`

1. Walk `DishComponent → Recipe → RecipeComponent`, recursing into `sub_recipe`.
2. Scale each sub-recipe's components by `requested_quantity / sub_recipe.yield_quantity`,
   converting units within the dimension first. (This is why `yield_quantity` is mandatory.)
3. Guard against cycles, cap depth at 5.
4. Aggregate by `(ingredient, dimension)` in base units. Convert cross-dimension only when
   `Ingredient.density_g_per_ml` is set; otherwise keep the lines separate. Treat an
   `IncompatibleUnits` between two counted units the same way — keep lines separate rather than
   inventing a number (D34).
5. Convert back to a human-friendly unit for display.
6. Optionally drop `is_staple` ingredients.

**Regeneration is idempotent.** It deletes only `source=GENERATED` items on the target list and
rebuilds them; manual items survive. If no shopping list exists, one named "Shopping List" is
created.

---

## 6. Security posture

Django's ORM parameterises queries and its templates escape output, so SQLi and reflected XSS
are largely handled by using the framework correctly. The real exposure, in priority order:

1. **IDOR / broken object-level authorization.** A missing queryset filter leaks data. Mitigated
   by the single `visible_to()` convention and dedicated permission tests on every endpoint.
2. **Visibility leaking through relations** — a private sub-recipe surfacing inside a shared
   parent's serialized output.
3. **File upload** (N1) — content-type sniffing, decompression bombs, SVG-borne XSS, path
   traversal. Validate with Pillow, re-encode, never trust the filename.
4. **SSRF** (N2) — the extractor fetches a user-supplied URL from a machine inside a home LAN.
   Block private/loopback/link-local ranges, re-validate every redirect hop, cap size and time.
   The single most dangerous feature in the backlog.
5. **Brute force on login** — DRF scoped throttle; accounts are admin-provisioned with no
   self-service lockout recovery.
6. **Mass JSON import** (09) — object-count caps, schema validation, and it must never let an
   importer set `owner` to another user.
7. **Temp passwords** — single-use, expiring, forced change on first login, session cycled on
   change.

Passwords use Django's default PBKDF2 hasher. Admins can reset a password to a new temp value;
they can never see an existing one.

---

## 7. Decisions & constraints

Binding decisions and the reasoning behind them. Append rather than rewrite; a reversed
decision is struck through with a note. Verbose implementation history has been dropped — what
remains is what a future session needs to respect.

### Decisions

| # | Decision |
|---|---|
| D1 | Django templates + HTMX, not a SPA. The REST API is still built for future native clients. |
| D2 | Django Admin, customized — not a bespoke admin UI. |
| D3 | Rating / favorite / times-made live on per-user `RecipeStats` / `DishStats` rows, not on the shared object. |
| D4 | All task plans written up front; nice-to-have designs will shift once the MVP is real. |
| D5 | `SECRET_KEY` must be supplied in `.env`; never auto-generated. Auto-generating into the data volume hides a backup-critical value and silently rotating it logs everyone out. `make secret` produces one. |
| D6 | Container entrypoint runs migrate/collectstatic every boot; seeds catalog and bootstraps an admin on first run only (volume-guarded). |
| D7 | Development in a `uv`-managed venv; the same `uv.lock` builds the image. Prevents "works on my machine" structurally. |
| D8 | One branch per task. Agents may cut branches but never commit, push, or merge. A finished task must be committed and merged before the next starts. |
| D9 | `TokenAuthentication` deferred from task 00 to task 01 (now landed) because `authtoken`'s initial migration FKs `AUTH_USER_MODEL`. `DEFAULT_AUTHENTICATION_CLASSES` is written explicitly. |
| D10 | Python pinned to 3.13 exactly, not "3.12+". `uv` fetches it; no system Python involved. |
| D11 | `ruff` excludes `Plan/`, `.claude/`, `MarkdownFiles/` via `extend-exclude` (not `exclude`, which would un-exclude `.venv`/`.git`). |
| D12 | `/api/schema/` and `/api/docs/` require authentication — drf-spectacular serves both to `AllowAny` by default, which would publish the API shape anonymously. `IsAuthenticated`, not `IsAdminUser`, so a future native-client dev can read the schema. |
| D13 | Python base image pinned by digest AND to a specific `uv` image/version, both recorded at build time, so a rebuild reproduces the same layers. |
| D14 | Runtime image builds with `uv sync --frozen --no-dev --group prod` — `gunicorn` is in the `prod` group and `--no-dev` alone would not include it. |
| D15 | Caddy's `SITE_ADDRESS` env var (default `localhost`) drives automatic HTTPS directly — no `tls internal`, no separate redirect block. Pointing it at a real domain gets a Let's Encrypt cert with no other change. |
| D16 | The container's SQLite `DATABASE_URL` default is supplied by `compose.yaml` (`sqlite:////app/data/db.sqlite3`), not baked into `.env.example`, because the data volume mounts at `/app/data` not `/app`. |
| D17 | `make secret` draws from Django's charset minus `$` — Docker Compose interpolates `$VAR` inside `.env` values and silently strips a `$` in a pasted `SECRET_KEY`. `.env.example` documents `$$` escaping for hand-typed values. |
| D18 | The entrypoint checks first-run command existence via `get_commands()`, and **each first-run command gets its own on-disk marker** (`.ran-seed_catalog`, `.ran-bootstrap_admin`), written only after it actually runs. A single shared marker was tried and broke: a command landing later would be skipped forever on an already-booted volume. |
| D19 | `psycopg[binary]` is an optional `postgres` dependency **group**, not a main dep, so a bare `uv sync` stays driver-free. The Docker image mirrors this with build arg `INCLUDE_POSTGRES` (default `false`). |
| D20 | `prod.py` `ALLOWED_HOSTS` always appends `"127.0.0.1"` (`env.list("ALLOWED_HOSTS") + ["127.0.0.1"]`) so the Compose healthcheck (`Host: 127.0.0.1`) still passes when a deployer points `ALLOWED_HOSTS` at a public domain — otherwise `app` never reports healthy and Caddy never serves. |
| D21 | `prod.py` (only) adds a `LOGGING` override sending `django` / `django.request` to stderr at `INFO`/`ERROR`. Without it, `DEBUG=False` 500 tracebacks are discarded on a deployment whose only telemetry is container logs. `django.request` is `propagate: False`. |
| D22 | A synchronised system clock is a documented build prerequisite (`README.md`). **Never** add `-o Acquire::Check-Valid-Until=false` / `Check-Date=false` to `apt-get` — that disables the check protecting against stale/replayed repo metadata. `Release file ... is not valid yet` means the clock is behind; `... is expired` means ahead. Fix with `chronyc makestep`. |
| D23 | `accounts.services.complete_password_change` does **not** call `update_session_auth_hash` (a service has no `request`). `set_password` alone invalidates every session including the actor's — stronger against the "stolen session dies at the reset" threat. The usability cost lands on **the view layer**, which must call `update_session_auth_hash(request, user)` right after so the user completing their own forced change is not logged out. Do not push `request` into the service to "fix" this. |
| D24 | `POST /api/auth/login/` applies `csrf_protect` directly, making it **browser-only in production** — confirmed with the owner, who stated there will never be a headless client. Prevents login CSRF. A future 403 here is not a bug; the answer if a headless client is ever needed is a token-minting endpoint, not loosening this. |
| D25 | Login throttling is one `ScopedRateThrottle` bucket (`5/min`, scope `login`) shared by `POST /api/auth/login/`, the HTML login view, and `/admin/login/`, and it **never locks an account** (no self-service recovery → account lockout would be a DoS lever). Prod depends on `NUM_PROXIES = 1` and a `FileBasedCache` in `prod.py`. Deferred to 10.5: an attacker holding one valid account gets a second budget (throttle keys on `user.pk` when authenticated). |
| D26 | `manage.py bootstrap_admin` has a `--force` flag that reactivates, promotes, and re-issues a temp password for whoever holds the target username. The grant and password write share one `transaction.atomic()`. Task 09 must reconcile it with the last-admin guard and audit trail (09.8, 09.13). |
| D27 | The bootstrapped first admin's temp password **is** retrievable afterward from `docker compose logs app` — stdout is the only channel before any admin can log in. Task 09's admin create-user flow is different (password returned in an HTTP response, written nowhere). Log rotation deferred to 10.7. |
| D28 | Caddy **replaces** an untrusted client's `X-Forwarded-For` rather than appending, so `NUM_PROXIES = 1` is the load-bearing control. The `header_up X-Forwarded-For {remote_host}` line in the `Caddyfile` is belt-and-braces now and becomes **harmful** the day a `trusted_proxies` global option is added (it would overwrite the real client IP). Comments in `Caddyfile` / `prod.py` still wrongly say Caddy appends — correcting them + strengthening `config/tests/test_caddyfile.py` is 10.8. |
| D29 | Adding `rest_framework.authtoken` also registers `authtoken.TokenProxy` in Django Admin, so `/admin/authtoken/tokenproxy/add/` mints a token for any user (superuser-only today). Task 09 decides: `admin.site.unregister(TokenProxy)` or keep it as an audited action. |
| D30 | `.env` and `.env.example` default `DEBUG=false`, which silently breaks static-file serving under `manage.py runserver` against a fresh checkout (CSS/JS 404, page still returns 200). Local `.env` is set `DEBUG=true`. Flipping `.env.example`'s default is left as a deliberate owner call. |
| D31 | `_cascade_grant_public` widening the actor's own dependencies to `PUBLIC` stays **irreversible on revert**, by the same asymmetry as "unsharing does not cascade." The `share` API response returns `cascaded_to` so a caller sees which of its objects a `PUBLIC` widening will affect. |
| D32 | `OwnedViewSetMixin.get_permissions()` composes three permission layers **additively** — the live `DEFAULT_PERMISSION_CLASSES`, the mixin's action-keyed ownership baseline (`IsOwner` / `CanCopy` / `IsOwnerOrReadOnly`), and any subclass- or `@action`-level `permission_classes`. A declared override can only **add** classes, never drop the baseline. Any task 04+ viewset narrowing permissions for one action must layer on top, never assign `permission_classes` as a full replacement. |
| D33 | `OwnedModel` carries an explicit `contains_owned_children: bool | None = None` opt-out, consulted by `core/tests/test_conventions.py`'s hooks-guard before its relation-walk heuristic. A leaf model reached through a two-parent join table (the `RecipeComponent` shape task 05 adds) is indistinguishable from a container to a relation walk, so a leaf declares `contains_owned_children = False` rather than silencing the guard with a no-op hook. Full contract in `core/README.md`. |
| D34 | **COUNT ↔ COUNT conversion contract.** `Unit.count_family: str` (blank for MASS/VOLUME). The **generic** family (`each`=1, `half dozen`=6, `dozen`=12) interconverts on real ratios via `to_base_factor`. Every packaging/piece unit (can, slice, clove, pinch, package, bunch, head, stalk, sprig, stick, leaf, piece) is its **own singleton family** and converts only to itself. `catalog.services.units.convert` raises `IncompatibleUnits` (naming both units) for any COUNT↔COUNT pair not sharing a non-empty family. Cross-dimension COUNT↔MASS/VOLUME stays categorically refused. Task 05's `flatten`/aggregation must treat that `IncompatibleUnits` like a missing density — keep the lines separate. |
| D35 | **`shared_with` is owner-only on read.** The share audience is itself sensitive (task 03 `design.md`: "the audience list is itself sensitive"), and the `/shares/` action already gates it to the owner. `OwnedSerializer.shared_with` is therefore a `SerializerMethodField` returning the audience only when `request.user` owns the object and `[]` for everyone else (a read-only holder, any viewer of a PUBLIC object). Every downstream owned resource inherits this. `core/README.md`'s "list it in `Meta.fields` if you want it in the response" still holds — the field stays in the response for all readers, it just carries `[]` for non-owners rather than leaking the list. First enforced on `Ingredient` (task 04). |

### Corrections to the original requirements

| # | Hole in `PlanToPlate-Requirments.md` | Resolution |
|---|---|---|
| C1 | Recipes contain recipes, but `Recipe` had no yield — a sub-recipe cannot be scaled | `yield_quantity` + `yield_unit` are required. |
| C2 | Nothing prevented a recipe cycle (A → B → A) | Cycle detection on save, max depth 5, in `recipes/services.py` on every write path. |
| C3 | "Many kinds of units" undefined | `Unit(dimension, to_base_factor)`. Convert within a dimension always; across only with a density. `Decimal`. |
| C4 | Rating/favorite/times-made can't live on a shared object | Per-user `RecipeStats` / `DishStats` (= D3). |
| C5 | Transitive visibility undefined — sharing a Dish with a private Recipe | Sharing cascades read-grants to children; refused if a child can't be granted. |
| C6 | Copy semantics undefined — reference or snapshot? | Deep snapshot with a `copied_from` pointer. |
| C7 | The planner had no way to tell a Protein from a Carb | Explicit `Recipe.role` field plus a `Tag` model. |
| C8 | Regenerating a meal plan would duplicate every shopping-list item | `ListItem.source` = MANUAL or GENERATED; regeneration replaces GENERATED only. |
| C9 | A random planner is an untestable planner | `MealPlan.seed` and a seeded RNG; partial results carry reasons. |
| C10 | The stated security concerns are the ones Django already handles | Real risks in section 6: IDOR first, then upload handling and SSRF. |
| C11 | "Deploy an AI agent to crawl the site" for recipe extraction | Parse `schema.org/Recipe` JSON-LD first; LLM only as fallback. |
| C12 | Stack gaps: no dependency manager, test framework, linter, API docs, background jobs, or backups | Filled in section 2. |

### Open questions

- Whether `MealPlan` should also be renderable as a `List` of kind `MEAL_PLAN`, or stay a
  distinct model that merely *generates* a list. Currently distinct — revisit in task 08.
- Whether user-created Ingredients should be promotable to `is_system` by an admin, to stop
  fifteen users creating fifteen "Chicken Breast" rows. Deferred to task 09.

---

## 8. Glossary

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
