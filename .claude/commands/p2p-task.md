---
description: Run the PlanToPlate dev → tester → reviewer pipeline for a task folder
argument-hint: <task-id, e.g. 05 or N2> [optional subtask range, e.g. 05.1-05.6]
allowed-tools: Agent, Read, Bash, Edit, Write, Glob, Grep
---

# PlanToPlate Task Pipeline — `$1`

Orchestrate the full implementation pipeline for the task folder matching `$1` in `Plan/`.
You are the orchestrator. You do **not** write application code yourself — the subagents do.

Scope for this run (may be empty): `$2` — either a subtask range like `05.1-05.6`, or a
free-form focus note.

## Setup

1. Resolve `$1` to a folder: `ls -d Plan/$1*`. If it does not resolve to exactly one folder,
   stop and ask.
2. Read `Plan/MILESTONES.md` and all three files in the resolved task folder.
3. Check the task's stated dependencies in `design.md`. If a prerequisite task is not marked
   complete in `MILESTONES.md`, **stop and tell the user** rather than building on sand.
4. **Determine this run's scope** (see below) and state it explicitly before dispatching, so
   the user can correct you before any work happens.
5. **Ensure the task's branch exists and is checked out** (see below).
6. Delete any stale `Plan/<task>/.review-findings.md` from a previous run — ask first, per
   `CLAUDE.md`.

## Branching — one branch per task, cut once

Every task gets exactly one branch, named `task/<folder-name-lowercased>`:

| Task folder | Branch |
|---|---|
| `05-Recipes` | `task/05-recipes` |
| `03-Ownership-And-Sharing` | `task/03-ownership-and-sharing` |
| `N2-Recipe-Extractor` | `task/n2-recipe-extractor` |

Run this decision before dispatching any agent:

1. **Already on the task's branch?** Do nothing. This is the normal resume case when a task
   spans several sessions.
2. **Branch exists but you are elsewhere?** `git checkout task/<name>`. **Do not create a
   second branch** — a task has one branch for its whole life, however many sessions it takes.
3. **Branch does not exist?** Create it from the default branch:
   `git checkout <default> && git checkout -b task/<name>`.

Creating and switching branches needs no permission. **Committing, pushing, merging, and
deleting branches all still do** — those stay with the user, per `CLAUDE.md` §2.

### Stop and ask the user if any of these are true

- **The working tree is dirty and you are about to create a new branch.** Since agents never
  commit, an unfinished task's work sits uncommitted in the tree; cutting a new branch would
  drag it onto the wrong task's branch. Say what is uncommitted and let the user commit or
  stash it first.
- **The prerequisite task's branch has not been merged into the default branch.** Branching
  from the default would start this task without the code it depends on. Tell the user which
  branch needs merging.
- **The repository has uncommitted changes to `Plan/` from a previous run.** Those are the
  ticked checkboxes and status updates — they belong to the previous task's branch.

Never merge, rebase, or delete a branch. Never commit. If the branch situation is anything
other than the three cases above, stop and describe it rather than guessing.

## Scoping a run — read this before dispatching

A task folder is a unit of *design*, not necessarily a unit of *one session*. Several tasks
have 12–15 subtasks, which is more than one agent run can do well. Attempting all of them in
one pass produces an agent that runs out of room halfway and a review that cannot hold the
whole change in view.

**Resume is automatic.** `tasks.md` checkboxes are the source of truth for what is done.
Always skip subtasks already ticked and start from the first unticked one — a later session
picks up exactly where the previous one stopped, with no handoff needed.

**Judge by the weight of the work, not the number of checkboxes.** Subtask count is a poor
proxy — task 02's twelve subtasks are mostly single template and CSS files, while task 05's
fourteen include the flattening service the whole app depends on. Read the subtasks before
deciding.

Decide scope in this order:

1. **If `$2` names a range** (`05.1-05.6`), do exactly those.
2. **If the task is on the always-split list below**, propose a split regardless of count.
3. **If twelve or fewer subtasks remain and they are mostly mechanical** — templates, CSS,
   config, serializers, thin CRUD over an existing service — do all of them in one run.
4. **Otherwise, propose a split**: a coherent chunk ending at a natural boundary (models done,
   or services done, or API done). State what you propose and what it defers, then proceed
   unless the user objects.

**Always split, whatever the count** — these carry the project's hardest logic or its security
guarantees, and a rushed pass on any of them is expensive to unpick later:

- `03-Ownership-And-Sharing` — the visibility keystone; every later task trusts it
- `05-Recipes` — cycle guard and the scale/flatten service
- `08-Meal-Planner` — the seeded generator and backtracking
- `09-Admin-Control-Center` — user provisioning and the JSON importer
- `10-Security-And-Deployment` — nineteen subtasks spanning audit, deploy, and backups
- `N2-Recipe-Extractor` — the SSRF guard

For these, keep chunks to roughly 4–6 subtasks so the reviewer can hold the whole change in
view. A review that cannot see the whole change is not a review.

Never split mid-subtask, and never end a run with a red suite or an un-migrated model change.
Each run must leave the tree working, because the next session starts by assuming it is.

## The loop (maximum 3 iterations)

**Stage 1 — `p2p-dev`.** Dispatch the `p2p-dev` agent with: the resolved task folder path, the
iteration number, and — on iterations 2 and 3 — an instruction to work `.review-findings.md`
as its work list. Wait for it to finish.

**Stage 2 — `p2p-tester`.** Dispatch the `p2p-tester` agent against the same task folder.
It runs the suite and audits coverage against `test-plan.md`.

**Stage 3 — `p2p-reviewer`.** Only if the tester returned PASS. Dispatch `p2p-reviewer`.
For a large or security-sensitive task (`03-Ownership-And-Sharing`, `08-Meal-Planner`,
`09-Admin-Control-Center`, `10-Security-And-Deployment`, `N2-Recipe-Extractor`), dispatch
**two reviewers in parallel in a single message** with distinct focus areas — one on
security and object-level authorization, one on correctness, data integrity, and design
conformance. Their findings merge into the same file.

**Branching.**
- Tester FAILs → skip review, append findings to `.review-findings.md`, return to Stage 1.
- Any reviewer says REQUEST CHANGES → append blocking findings, return to Stage 1.
- Tester PASSes and all reviewers APPROVE → exit the loop and go to Handoff.
- Three iterations without convergence → **stop**. Do not start a fourth. Report what is
  still failing and hand it to the user; a loop that cannot converge in three passes has a
  problem in the plan files, not in the code.

## Handoff — the pipeline always ends with the human

When the loop converges, **stop and notify the user for approval.** Present:

1. **Task `$1` is ready for your review** — one line on what now works that did not before.
2. Every file created or modified, grouped by area.
3. The final pytest summary and ruff result, as raw output.
4. Non-blocking suggestions the reviewers raised that you did not action.
5. Any deviation from `design.md`, flagged clearly.
6. How to see it working — the URL to visit or the command to run.

Then stop.

**Do not** mark the task complete in `Plan/MILESTONES.md`, and **do not** commit anything.
Both wait on explicit human approval.

If this run covered only part of the task, say so plainly — which subtasks are done, which
remain, and the exact command to continue (`/p2p-task 05` picks up from the first unticked
subtask). Set the task's status to `IN PROGRESS` in `MILESTONES.md` with a note naming the
last completed subtask.

Once the user approves a run that finishes the **final** subtask, set the status to
`AWAITING APPROVAL` → `COMPLETE`, update the decision log if this task settled anything future
sessions need to know, and ask whether they want it committed.
