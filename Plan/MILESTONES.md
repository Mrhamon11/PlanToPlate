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
| 04 | [Units & Ingredients](04-Units-And-Ingredients/design.md) | IN PROGRESS | — | 04.1–04.5 done: `Unit` + `Dimension`, `Tag`, conversion service, `Ingredient` model, seed data + `seed_catalog`. 04.6–04.12 implemented, awaiting tester + reviewer: `catalog/` serializers, API viewsets + filters (staff-gated Unit/Tag writes, `POST /api/units/convert/`, `IngredientViewSet`), protected-delete → 409 (`core/exceptions.py`), ingredient list/detail/form/quick-add HTMX screens, `_partials/_unit_select.html`, share/copy wired to task 03's partials. Migration `catalog/0002` adds `Unit.abbrev` unique. Ingredient seed drops `visibility=PUBLIC` (readable via `is_system`). See D34, D35 (`shared_with` serialized owner-only in `OwnedSerializer`). `test_delete_in_use_returns_409` real end-to-end case deferred to task 05 (nothing PROTECTs `Ingredient` until `RecipeComponent`). Resume with `/p2p-task 04`. |
| 05 | [Recipes](05-Recipes/design.md) | NOT STARTED | — | Cycle guard, scale/flatten service. |
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
