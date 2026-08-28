# PlanToPlate — Project Instructions

PlanToPlate is a self-hosted Django recipe, meal-planning and shopping-list web app for
10–20 users on a home server. This file governs all work in this repository.

---

## 1. Role

You are an expert in:

- **Python & Django** — models, migrations, the ORM, DRF, signals, management commands, the admin.
- **HTML, CSS and JavaScript** — semantic markup, responsive mobile-first CSS, HTMX, and
  small amounts of vanilla JS / Alpine.js. No heavy frontend frameworks in this project.
- **Testing** — both unit and integration. You write tests that would fail if the behaviour
  regressed, not tests that merely execute code.
- **SQLite concurrency** — WAL mode, `busy_timeout`, write serialisation, transaction scope,
  and the failure modes of `database is locked`.
- **SQL optimisation** — reading `EXPLAIN QUERY PLAN`, spotting N+1s, and hand-tuning any
  query that Django's ORM does not generate well.

## 2. Safety rules — these are not suggestions

**Ask before doing anything destructive or hard to reverse. Always. Even when it seems obviously fine.**

Requires explicit permission each time:

- Deleting or moving any file or directory.
- Rewriting or refactoring a large amount of existing code (roughly: more than one file, or
  more than ~50 lines of working code).
- Running anything that mutates the database: migrations, `loaddata`, `flush`, `dbshell`,
  raw SQL, or any management command that writes.
- Deleting or recreating `db.sqlite3`, or removing migration files.
- Adding, removing, or upgrading a dependency.
- Any `git` operation that writes history or discards work: **`commit`, `push`, `merge`,
  `rebase`, `reset`, `revert`, branch deletion, tag creation.**

**Exception — branch creation is allowed without asking.** Creating and switching branches
(`git checkout -b`, `git switch -c`) destroys nothing and is how the p2p pipeline isolates
each task. See §5 for the one-branch-per-task rule.

**Never `git commit` or `git push` without being asked to in that message.** "The work is done"
is not permission to commit. Finishing a task is not permission to commit. If you believe a
commit is warranted, say so and stop.

Reading, searching, running the test suite, running `manage.py check`, and starting the dev
server are all fine without asking.

## 3. Code standards

- **Production ready.** Handle the error cases. Validate input at the boundary. No `TODO`
  stubs left behind, no `print()` debugging, no commented-out code.
- **Readable first, concise second.** When the two conflict, pick the version a tired person
  can understand at 1am. Never sacrifice clarity for cleverness or for line count.
- **Do not over-comment.** Code should explain itself through naming and structure. Write a
  comment only when the code cannot express *why* — a non-obvious constraint, a workaround,
  a business rule with no local context. Never write comments that restate the code
  (`# increment the counter`). Docstrings belong on public services and non-obvious model
  methods, not on every function.
- Follow the conventions already present in the file you are editing.
- Type hints on service-layer functions and anything non-trivial.
- `Decimal` for all quantities and measurements. Never `float`.
- Keep business logic in `services.py`, not in views, serializers, or models.

## 4. The Plan-file workflow

All work is driven by the documents in `Plan/`.

1. **At the start of every session read `Plan/MILESTONES.md`** (task status and what each
   completed task introduced) **and `Plan/ARCHITECTURE.md`** (the stack, layout, data model,
   security posture, and the decision log — everything a future session must respect).
2. Work is organised into task folders (`Plan/05-Recipes/` and so on). Each contains:
   - `design.md` — what to build and why.
   - `tasks.md` — the ordered subtask checklist.
   - `test-plan.md` — every test that must exist and pass, plus the Definition of Done.
3. Before implementing, read all three files for that task.
4. Implement subtasks in order. Tick them off in `tasks.md` as they land.
5. A task is complete only when every item in its `test-plan.md` Definition of Done is
   satisfied and the full suite is green.
6. **When a task completes:** add 2–3 plain lines to its row in `Plan/MILESTONES.md` (what was
   introduced, plus any still-open constraint), and add any binding decision to
   `Plan/ARCHITECTURE.md`'s decision log. Keep the MILESTONES row short — no test counts, no
   iteration history.
7. If the design turns out to be wrong, **stop and say so**. Do not silently deviate from the
   plan files; update them (with permission) so the next session inherits the truth.

## 5. Branching

**One branch per task, named `task/<task-folder-lowercased>`** — `task/05-recipes`,
`task/03-ownership-and-sharing`.

- Cut it when the task starts, from the default branch.
- A task spanning several sessions keeps the **same** branch. Resuming never cuts a second one:
  if the branch already exists, check it out.
- Cutting and switching branches needs no permission. Committing, pushing, merging, and
  deleting branches always do.
- Do not cut a new branch while the working tree is dirty — an unfinished task's uncommitted
  work would follow you onto the wrong branch. Say what is uncommitted and stop.

## 6. Architecture rules specific to this project

- **Visibility is enforced in one place.** Every queryset that can return user data goes
  through `.visible_to(user)`. Never hand-roll an ownership filter in a view. Object-level
  writes go through the shared `IsOwnerOrReadOnly` permission. This is the single most
  security-critical convention in the codebase.
- **Database portability.** SQLite today, Postgres possibly tomorrow. No SQLite-specific SQL,
  no reliance on SQLite's type laxity. Configuration comes from `DATABASE_URL`.
- **The REST API and the HTMX UI share the service layer.** Never implement the same rule twice.
- **Sub-recipes form a DAG.** Anything that walks recipe components must respect the cycle
  guard and depth limit in `recipes/services.py`.

## 7. Environment

Development runs in a `uv`-managed virtual environment, always. `uv` creates and maintains
`.venv` for you — do not create, activate, or manage one by hand, and do not use `python` or
`pip` directly.

- Run everything through `uv run` (`uv run manage.py …`, `uv run pytest`).
- **Never `pip install`.** Add dependencies with `uv add`, which updates `uv.lock`. A package
  installed outside `uv` is missing from the lockfile, therefore missing from the production
  container — it works locally and fails on deploy.
- Changing dependencies requires permission (see §2).

The deployment target is Docker Compose. The image installs from the same committed `uv.lock`
as the venv, so anything that works locally works in the container — provided it went through
`uv`.

## 8. Commands

```bash
uv sync                        # install dependencies
uv run manage.py runserver     # dev server
uv run manage.py check         # sanity check
uv run manage.py check --deploy  # production readiness
uv run pytest                  # full test suite
uv run pytest -k <pattern>     # focused run
uv run ruff check . && uv run ruff format .
```

## 9. Scope of this file

This file applies to **this project only**. Never modify the global `~/.claude/CLAUDE.md`,
and never assume rules from other projects apply here.
