# PlanToPlate — Task Status

> **Read this at the start of every session.** It tracks what is done and what each completed
> task introduced. Architecture, conventions, the data model, and the decision log live in
> [`ARCHITECTURE.md`](ARCHITECTURE.md) — read that before writing or reviewing code.
>
> **When a task completes, add 2–3 lines to its row** — what was introduced, in plain terms,
> plus any still-open constraint the next task must know. No test counts, no iteration history.
> Anything a future session must *respect* goes in `ARCHITECTURE.md`'s decision log instead.

---

## Task status

Statuses: `NOT STARTED` · `IN PROGRESS` · `AWAITING APPROVAL` · `COMPLETE` · `BLOCKED`

| # | Task | Status | Completed | What it introduced |
|---|---|---|---|---|
| 00 | [Foundations](00-Foundations/design.md) | COMPLETE | 2026-08-19 | Project skeleton, settings split, SQLite concurrency config, Docker Compose + Caddy, container entrypoint (migrate/collectstatic every boot; seed + bootstrap-admin first-run only, per-command markers), `DATABASE_URL` portability seam, optional `postgres` dependency group. |
| 01 | [Users & Auth](01-Users-And-Auth/design.md) | COMPLETE | 2026-08-24 | Custom `User` model (so domain models may reference `AUTH_USER_MODEL`), session auth, `TokenAuthentication` enabled, temp-password flow (single-use, expiring, forced change), `bootstrap_admin` command (+ `--force`), one shared login throttle bucket. See D23–D27, D29. |
| 02 | [UI Shell](02-UI-Shell/design.md) | COMPLETE | 2026-08-24 | `base.html`, hand-written mobile-first CSS with light/dark tokens, responsive nav (no JS), five shared partials, htmx + Alpine vendored into `static/js/`, `HtmxMiddleware` + `HtmxTemplateMixin` / `MessageMixin` / `OwnedObjectMixin`, styled 403/404/429/500 pages, `core:home` dashboard shell. See D30. |
| 03 | [Ownership & Sharing](03-Ownership-And-Sharing/design.md) | COMPLETE | 2026-08-26 | The visibility keystone infrastructure that tasks 04–08 inherit: `OwnedModel` + `visible_to()`, `IsOwnerOrReadOnly`, `OwnedViewSetMixin` (additive 3-layer permission composition), `OwnedSerializer` / `OwnedObjectMixin` read-only-field guards, sharing + deep-copy services with child cascade, `_share_modal` / `_copied_from` partials, `test_conventions.py` regression guards. No live UI yet. See D31–D33. NB: `_copied_from.html` follows the original's live title/owner via FK — a renamed/now-private original can leak its current name through a copy; real fix deferred to whichever task first renders it. |
| 04 | [Units & Ingredients](04-Units-And-Ingredients/design.md) | COMPLETE | 2026-08-29 | `Unit` + `Dimension` + `Tag`, unit-conversion service (`convert` / `to_base` / `humanize`, `IncompatibleUnits`), `Ingredient` as an `OwnedModel` leaf (`contains_owned_children = False`), and ~30 units / ~35 tags / ~150 ingredients seeded `is_system` via idempotent `seed_catalog`. `catalog/` serializers + API (read-only Unit/Tag with staff writes, `POST /api/units/convert/`, `IngredientViewSet` + `IngredientFilter`), protected-delete → 409 (`core/exceptions.py` `Conflict`), ingredient list/detail/form/quick-add HTMX screens, `_partials/_unit_select.html`, share/copy on task 03's partials. See D34 (COUNT↔COUNT family contract), D35 (`shared_with` owner-only on read). Still open: the real end-to-end `test_delete_in_use_returns_409` is deferred to task 05 (nothing PROTECTs `Ingredient` until `RecipeComponent`). |
| 05 | [Recipes](05-Recipes/design.md) | COMPLETE | 2026-09-02 | `Recipe` / `RecipeComponent` (ingredient-XOR-sub_recipe DB check, `PROTECT` deletes) / per-user `RecipeStats`. Cycle guard (`assert_no_cycle`, `MAX_DEPTH = 5`) on every sub-recipe write path — serializer + HTML form; admin → 09.4. `scale` / `flatten` / `aggregate` with sub-recipe yield scaling and irreconcilable-dimension splitting (never invents a density). REST `RecipeViewSet` + filters; HTMX list / detail / form (dynamic rows, `visible_to` ingredient typeahead + quick-add, cycle-filtered sub-recipe typeahead) / print / owner-only delete. `recipes/services/deletion.py` builds the "used as a sub-recipe in…" 409 (names visible parents, counts hidden ones) — shared by REST `DELETE` and the HTML delete view. Print inlines each sub-recipe's own ingredients (`with_component_graph`). Copy reuses a child the actor already copied instead of duplicating it (D37). `FlatLine.from_recipes` carries the **full root→leaf recipe chain** per line, not only the recipe that directly lists the ingredient — tasks 07/08 inherit this. `Recipe.role` is a 9-value set (adds `SIDE`, `BREAKFAST` — D36). Still open: `serving` yield-unit default falls back to `each` (11.10); share-revoke / unpublish does not cascade to sub-recipes (11.11, and D31); collapsible list filters + typeahead keyboard nav (11.12/11.13). |
| 06 | [Dishes & RecipeBooks](06-Dishes-And-RecipeBooks/design.md) | NOT STARTED | — | |
| 07 | [Lists & Shopping](07-Lists-And-Shopping/design.md) | NOT STARTED | — | Generated vs manual provenance. |
| 08 | [Meal Planner](08-Meal-Planner/design.md) | NOT STARTED | — | Seeded generator, idempotent regeneration. |
| 09 | [Admin Control Center](09-Admin-Control-Center/design.md) | NOT STARTED | — | Django Admin + custom actions. Owns the D26/D29 reconciliation. |
| 10 | [Security & Deployment](10-Security-And-Deployment/design.md) | NOT STARTED | — | Backups, TLS, prod checklist. Owns D25/D27/D28 follow-ups (10.5, 10.7, 10.8). |
| 11 | [Task Bug Fixes](11-TaskBugFixes/tasks.md) | NOT STARTED | — | Standing catch-all for reviewer findings deliberately deferred rather than fixed in-task. No `design.md` / `test-plan.md` yet — written per-subtask when picked up. |
| N1 | [Images & Camera](N1-Images-And-Camera/design.md) | NOT STARTED | — | Nice to have. |
| N2 | [Recipe Extractor](N2-Recipe-Extractor/design.md) | NOT STARTED | — | Nice to have. SSRF-critical. |
| N3 | [Social Feed](N3-Social-Feed/design.md) | NOT STARTED | — | Nice to have. |
| N4 | [PWA & Polish](N4-PWA-And-Polish/design.md) | NOT STARTED | — | Nice to have. |

**Dependency order:** 00 → 01 → 02 → 03 → 04 → 05 → {06, 07} → 08 → 09 → 10.
Nice-to-haves: N1 after 05 · N2 after 05 and N1 · N3 after N1 and 06 · N4 after 02 and 08.
Task 11 is off this chain — picked up whenever convenient once the task that surfaced a given
subtask is done.

Tasks 04–08 are each vertical slices: models, services, REST API, HTMX screens, and tests.
Every one ends with something you can click.

---

## Session checklist

**Starting:** read this file → read [`ARCHITECTURE.md`](ARCHITECTURE.md) → read the task's
`design.md`, `tasks.md`, `test-plan.md` → confirm prerequisite tasks are COMPLETE →
`uv sync && uv run pytest` to confirm you start green.

**Finishing:** full suite green → `ruff` clean → every Definition of Done item in the task's
`test-plan.md` satisfied → subtasks ticked in `tasks.md` → this file's row updated (2–3 lines)
→ any binding decision added to `ARCHITECTURE.md` → ask before committing.
