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
| Language | Python 3.12+ | |
| Framework | Django 5.x | |
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

DRF `TokenAuthentication` is *also* enabled, for a future native app. It is not used by the
web UI.

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
| 00 | [Foundations](00-Foundations/design.md) | NOT STARTED | — | Repo, tooling, Django scaffold, Docker |
| 01 | [Users & Auth](01-Users-And-Auth/design.md) | NOT STARTED | — | Custom User **must** land before any data model |
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
