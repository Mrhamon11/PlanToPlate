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
    role: PROTEIN | CARB | VEGETABLE | ONE_POT | SAUCE | DESSERT | SIDE | BREAKFAST | OTHER   # D36
    tags M2M(Tag)

RecipeComponent
    recipe → Recipe, position
    ingredient → Ingredient?  XOR  sub_recipe → Recipe?    # DB CHECK: exactly one
    quantity: Decimal, unit → Unit, note

Dish(OwnedModel)          ── DishComponent(dish, recipe, servings: Decimal, position)
    name, description, tags M2M(Tag)                  # servings = that recipe's scale factor
RecipeBook(OwnedModel)    ── RecipeBookEntry(book, recipe, section, position)
    name, description, default_ordering               # section is free text, per book

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

UserObjectStats(abstract)   # core/models.py — the shared per-user stats shape (D38)
    user, rating 0–5, is_favorite, times_made, last_made_at

RecipeStats(UserObjectStats)  recipe   # unique (user, recipe)
DishStats(UserObjectStats)    dish     # unique (user, dish)
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
  recording provenance. No pointers into someone else's data. Exception: a child you have
  **already copied** is reused, not copied again (D37).
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
8. **`max_total_minutes`** — time budget per meal, measured as `max(prep) + sum(cook)` across
   the dish's recipes (a cook prepping in parallel), not a plain sum (D49).

Profiles are saved and named. `MealPlanProfile.exclude_staples` is a **9th** knob but a
shopping-list rendering option, not one of the eight generator gears — acknowledged here so it
is not later read as a violation of the cap (D50).

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
| D37 | **A deep copy reuses a child the actor has already copied, rather than copying it again.** Task 03's plan said copy-dedup was out of scope; task 05's dev test found this is not optional for `Ingredient` — its `(owner, name)` uniqueness makes a second copy unstorable, so copying two recipes that share a private ingredient (or re-copying one recipe) raised `IntegrityError`. `recipes.models._copy_or_reference` now resolves a child to an existing copy the actor owns — matched on `copied_from`, then (for `Ingredient` only) on name — before falling back to `Copier.copy`. Trade-off: a re-copied sub-tree is **shared** with the earlier copy, not duplicated. `Copier.actor` is exposed for this. Any future `OwnedModel` with a `copy_children` hook and a per-owner uniqueness constraint must apply the same rule. |
| D36 | **`Recipe.role` has 9 values, not 7.** Task 05's `design.md` lists `PROTEIN / CARB / VEGETABLE / ONE_POT / SAUCE / DESSERT / SIDE / BREAKFAST / OTHER`; §4 above originally carried only the first six plus `OTHER`. `SIDE` and `BREAKFAST` are real planner categories (a side dish is not a `VEGETABLE`; breakfast recipes must be selectable for the planner's optional breakfast slot, §5 gear 1) and the implementation follows `design.md`. `default=OTHER`, `db_index=True`. Adding a tenth role is a decision to record here, like the planner's eight gears. |
| D38 | **Per-user stats live on the abstract `core.UserObjectStats` base, and its `user` FK uses `related_name="%(class)s_records"`.** `RecipeStats` and `DishStats` are the same model with a different foreign key; task 06 factored the shape out rather than copying it, because "two copies of this model is how the third one gets written subtly differently." A concrete subclass adds only its object FK and a `UniqueConstraint` on `(user, <that key>)`. The `related_name` is deliberate: Django's default `%(class)ss` yields the awkward `user.recipestatss` **and** silently renames task 05's `user.recipe_stats`, so the base was given a clean name inside task 06's own migration (`recipes/0003_alter_recipestats_user`) rather than costing a second one post-merge. Nothing reads the reverse accessor today — every `services.stats` module queries the concrete model — so any future reader gets `user.recipestats_records` / `user.dishstats_records`. A third per-user stats model subclasses the base; it does not copy it. |
| D39 | **No `hx-confirm` anywhere.** It calls `window.confirm()`, which renders the browser's native dialog — unstyled, and prefixed with "localhost:8000 says" in Chrome. Task 06's dev test caught the one instance in the codebase (removing a recipe from a book). Every destructive confirmation goes through a real page or the shared `#modal` fragment instead, the pattern `_copy_book_confirm.html` / `recipebook_copy_confirm.html` already established: a GET renders the confirm into `#modal`, its form POSTs with an explicit `hx-target`, and the response clears `#modal` via `hx-swap-oob`. The same episode is the reason for the corollary: **an HTMX control that swaps something other than itself must name an `hx-target`.** HTMX's default target is the triggering element, so an `hx-post` without one injects the whole re-rendered fragment into the button that fired it — which looks correct until you stop reloading the page. |
| D40 | **A shared `List` is read-only for the recipient.** They can open it but cannot check an item off, add a line, reorder, or clear it — enforced by `IsOwnerOrReadOnly` on the API and `OwnedObjectMixin` / the `_owned_list` helper on the HTML views. Collaborative editing is out of scope: task 03 grants read, not write, and a shared shopping list two people both tick is a different feature with concurrency questions this app does not need. Pinned by `test_shared_list_is_read_only` (API + view). |
| D41 | **Tombstone `pre_delete` receiver (`lists/signals.py`).** The `lists_listitem_has_content` check constraint and `SET_NULL` on `ListItem.recipe` / `dish` / `ingredient` collide for a content-only item — the moment its one FK nulls, the row is invalid and the delete transaction aborts. A `pre_delete` receiver on Recipe / Dish / Ingredient stamps fallback `"(deleted recipe)"` / `"(deleted dish)"` / `"(deleted ingredient)"` text onto referencing content-only items *before* the collector nulls the FK. Items that carry their own text are left untouched. Side effect: registering these receivers disables `can_fast_delete` for those three models app-wide and fires one filtered (usually no-op) `UPDATE` per instance on every delete. Blind spot (deferred to tasks 08 and 09): a generated item carrying **two** FKs (`ingredient` + `dish`, which `populate_shopping_list` writes) — each receiver skips it because the other FK is still set, so a same-pass delete of both still violates the constraint. CO-1 closes only the serializer path. The realistic trigger is not the API but **admin user-deletion** (task 09): `owner` is `CASCADE`, so deleting a user collects that user's recipes, dishes and ingredients in one pass, and a two-FK generated item on *another* user's list is caught in the crossfire. Task 09's delete-user flow must reconcile this — either give the receivers a two-FK branch or stamp the tombstone before the cascade runs. |
| D42 | **No dish-level dedupe in `populate_shopping_list`.** A dish scheduled twice in a plan aggregates to 2× — a repeated dinner needs double the groceries. Same as calling `add_dish_to_list` twice (07.1 review, finding 2). |
| D43 | **List-item provenance = contributing dish, single-contributor only.** A `GENERATED` `ListItem` records its contributing dish on `ListItem.dish`, but only when exactly one dish fed that aggregated ingredient line; when several dishes share an ingredient, `dish` is null and `generated_from` (the plan) is the provenance. The full root→leaf recipe chain `FlatLine.from_recipes` carries is deliberately not persisted — at the shopping-list layer the useful "why is this here" is "which dinner", not the sub-recipe nesting path. As of the 2026-09-05 dev-test round (07.21) the list UI renders **no** "from …" label — the contributing dish stays on `ListItem.dish` as data only; task 08 decides how to surface provenance on a planner-generated list. |
| D44 | **`planner.MealPlan` minimal stub.** Task 07 ships `planner/models.py::MealPlan(OwnedModel)` with one `name` field and `contains_owned_children = False`, purely so `ListItem.generated_from`'s lazy FK target resolves at system-check time (a bare string reference to a non-existent model fails `manage.py check`). **Task 08 owns its real shape** (`start_date`, `days`, `profile`, `seed`, `shopping_list`, `MealPlanProfile`, `MealPlanEntry`, the generator) and must re-decide `contains_owned_children` / the sharing-cascade posture once it gains `entries` / `shopping_list`. ~~Task 07's stub sets `contains_owned_children = False` (no cascade).~~ **Re-decided in task 08 (D47): sharing a `MealPlan` cascades read-grants to its scheduled dishes and their recipe graphs, exactly like sharing a `Dish`. The `contains_owned_children = False` line was removed (back to `None`); `share_dependencies()` and `copy_children()` are both overridden.** |
| D45 | **A user can edit any list item's `quantity` / `unit` (`lists.services.update_item`).** An aggregated line ("2 cups chicken breast") is often not a buyable amount — the number is the user's to correct and the app assumes nothing. `update_item` is the single validation choke point for both the REST `PATCH` and the HTMX edit: rejects a non-finite / negative / >3-decimal-place / over-`9999999.999` quantity, and a `unit` set with no `quantity`; a valid `Unit` is never rejected for dimensional incompatibility. An edit does **not** change `ListItem.source`. Consequence for task 08: a manual quantity edit to a `GENERATED` line is lost when `populate_shopping_list` regenerates that plan — the same accepted trade-off as a lost checked state, covered by the same regenerate warning. Whether an override should survive regeneration is a task 08 decision. |
| D46 | **Editable / collaborative sharing is deferred to task 13.** Task 07 (see D40) keeps the task-03 model: a shared object is read-only for the recipient, who copies it to modify. Task 13 will add an *edit* grant alongside view-only, for recipes / dishes / books / lists — spec required first (`Plan/13-Collaborative-Sharing/design.md`), the driving open question being concurrent edits to one shared shopping list. |
| D47 | **Sharing a `MealPlan` cascades read-grants to its scheduled dishes and their recipe graphs** (reverses D44's non-cascade clause). `MealPlan.share_dependencies()` returns the entries' distinct dishes (repeats deduped, unfilled slots skipped); `core.services.sharing.walk_dependencies` pulls each dish's component recipes / sub-recipes / ingredients; `_validate_cascade` **refuses the share** — naming the blocking dish — if a scheduled dish the plan owner does not own is not already visible to the recipient. `contains_owned_children` is back to `None`; both `share_dependencies` and `copy_children` are overridden, `copy_children` a deliberate **no-op** (plan copy is out of scope, `MealPlanViewSet.copy` is `405`). Unsharing does not cascade back (D31). The generated `shopping_list` is **not** a share dependency — it is a separately-owned, separately-shared `List`, and deleting a plan removes its entries but not that list. Latent asymmetry (accepted): `walk_dependencies` roots the walk one level above each dish, so a plan-share over a near-maximal recipe graph can raise `DepthExceededError` where sharing that dish directly would pass — `share()` turns it into a user-facing refusal, and real nesting is shallow. |
| D48 | **`MealPlan.profile_snapshot` is owner-only on read** (D35 pattern): a `SerializerMethodField` returning `{}` for any non-owner reader of a `SHARED` / `PUBLIC` plan, and `plan_detail.html` gates the profile name on `is_owner` — otherwise a sharee would see the owner's `excluded_ingredients` (allergy list), `excluded_tags`, `tag_limits` and profile name. The snapshot is **server-generated** (a client cannot inject one) and stores the gears **plus `profile_id`**, with exclusions recorded as **names** not FKs so it still reads after a tag/ingredient is deleted. Accepted tombstoning boundary: `MealPlanEntrySerializer` nulls `dish_name` for a dish the viewer cannot see but still returns the raw integer `dish` id — consistent with the reviewed task-07 `ListItemSerializer` pattern; the id is not dereferenceable (`/api/meals/dishes/<id>/` is `visible_to`-scoped). |
| D49 | **Generator behavioural contract.** Strict `BALANCED` has **no dish-level fallback** — it selects only a dish covering protein + carb + vegetable, or composes one from recipes; a partial / one-pot dish is never substituted (owner-confirmed). `MIX` = per-slot alternation between a `BALANCED` lean and a `ONE_POT` lean, starting phase drawn from the RNG; each lean falls back to any dish (unlike strict `BALANCED`). `source_scope`'s `SHARED` value means "mine + shared with me" (cosmetic rename from `MINE_AND_SHARED`). Composition is attempted for any BALANCED-leaning slot **before** backtracking; composed dishes **degrade rather than repeat** — `compose_balanced_dish` refuses a recipe-trio whose signature is already placed in the plan, so a thin recipe library composes one BALANCED dinner and leaves the surplus slots honestly unfilled. Gear-8 `max_total_minutes` is measured as **`max(prep) + sum(cook)`** (`meals/services/dishes.total_minutes_for`), modelling a cook prepping in parallel — it diverges from the "prep + cook" shorthand in §5. `favorites_bias = 0` (or any all-zero weight vector) falls back to a uniform draw in `_weighted_pick`, protecting the admin / ORM / fixture paths, not just the API. `excluded_tags` matches a dish's own `Dish.tags` only — an untagged or auto-composed dish is not removed by "exclude every tag"; excluded **ingredients** (checked through the flattened sub-recipe graph) are the allergy filter. |
| D51 | **"Shared with you" orders by the object's `updated_at`, and no `shared_at` through model is added.** The home dashboard's shared-with-you panel (task 12) wants "recently shared" but `OwnedModel.shared_with` is a plain `ManyToManyField` with no timestamp. A through model carrying `shared_at` would touch the task-03 visibility keystone and every model that inherits `OwnedModel` — a large, security-sensitive change for one panel's sort order. Rejected: the panel orders by `updated_at` instead (`core.services.dashboard._shared_with_you`), an approximation that is good enough for a glance and costs nothing. If a real "shared on" date is ever needed (an activity feed, share history), that is the point to reconsider the through model — deliberately, across all `OwnedModel` subclasses at once. |
| D50 | **Planner persistence & UX contract.** Persist is **stateless** — `POST /api/planner/plans/` and the HTML `PlanSaveView` store no preview; they re-run the deterministic generator from `{profile, start_date, seed, days}` (+ `name`) and save (C9 guarantees byte-identical output; `PlanResultSerializer` returns `seed` for the client to echo back). `regenerate` / `reroll` **draw a fresh random seed** each call; pass the plan's own seed to rebuild a week. A manual dish swap **clears `is_locked`** on both the HTML (`PlanEntrySwapView`) and API (`MealPlanEntrySerializer.update`) paths — an explicit `is_locked` in the PATCH payload still wins. Regeneration **keeps a locked slot's `note`, drops an unlocked slot's**; a locked-but-empty slot is carried through unfilled and **not** counted toward "N slots open". A cleared `no_repeat_days` falls back to `planner.models.DEFAULT_NO_REPEAT_DAYS` (14); an explicit `0` is a deliberate "no window". `MealPlan.name` is `blank=True` (not the required field `design.md` specifies) — a cleared name renders as "Meal plan" / "Untitled plan", matching the generate flow. `preview-shopping-list` is **owner-only**, not `IsOwnerOrReadOnly`. Task 08's shopping-list work is **orchestration only**: the read-only compute path was extracted into `lists.services._flatten_dishes_to_lines` + `preview_shopping_list` (behaviour-preserving, one file) so preview and write share one path and no flatten / aggregate / scale logic lives in `planner/`. |
| D52 | **Home dashboard read-model contract.** `core.services.dashboard.build_dashboard(user)` is the single choke point — it runs every panel's query once and returns a `DashboardContext` dataclass; the HTML `HomeView` and `GET /api/dashboard/` (`core.api.DashboardAPIView`, serialised by `core.serializers`) both consume it and assemble nothing, so no panel rule is written twice. **Every panel query goes through `.visible_to(user)`**, and any panel built from stored state (recently-viewed, favourites) re-resolves each row live because access can have been revoked since it was recorded. `core.RecentView` is **deliberately not an `OwnedModel`** — private per-user telemetry (generic FK, one `update_or_create`-bumped row per `(user, object)`, capped by `core.services.recent.RECENT_LIMIT`), filtered only by `user=<requester>`, never scoped by object ownership, never serialised cross-user. Panels with nothing to say are absent (`None` / `[]`); the five section links are the floor the page degrades to. "Shared with you" (explicit shares) and "Public from others" (`PUBLIC` only) are mutually exclusive and expose only the owner's username (D35). Accepted deviations from `design.md`, all recorded in `Plan/12-Home-Dashboard/tasks.md`: `api_urls.py` split from `urls.py` (per-app convention); an `EmptyPanel` CTA replaces hidden flagship panels; an extra "Public from others" panel; per-panel item caps. Fragment endpoint `core:dashboard-panel` rebuilds the whole context to render one panel (only the "suggestion" re-roll uses it today) — `Plan/BACKLOG.md` carries the follow-ups. |

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

- ~~Whether `MealPlan` should also be renderable as a `List` of kind `MEAL_PLAN`, or stay a
  distinct model that merely *generates* a list.~~ **Resolved (task 08): stays a distinct
  model.** `MealPlan` / `MealPlanEntry` carry the day/slot grid and the generator; a plan
  *generates* a `kind=SHOPPING` `List` via `populate_shopping_list` but is never itself
  rendered as a `List`. The generated list is separately owned and separately shared; deleting
  the plan removes its entries, not the list (D47).
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
