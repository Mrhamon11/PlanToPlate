---
description: Dispatch only the p2p-dev (implementation) stage of the PlanToPlate pipeline
argument-hint: <task-id, e.g. 05 or N2> [optional subtask range, e.g. 05.1-05.6]
allowed-tools: Agent, Read, Bash, Edit, Write, Glob, Grep
---

# PlanToPlate — dev stage only — `$1`

Run **only** the implementation stage for the task folder matching `$1` in `Plan/`. This is the
split-session counterpart to `/p2p-task`: the tester and reviewer run in their own sessions via
`/p2p-task-test` and `/p2p-task-review`. You are the orchestrator; you do not write application
code yourself.

Scope for this run (may be empty): `$2`.

## Setup, branching, scoping

Read `.claude/commands/p2p-task.md` and follow its **Setup**, **Branching — one branch per
task**, and **Scoping a run** sections exactly. Same folder resolution, same dependency check,
same one-branch-per-task rules (create from the default branch only if it does not exist; never
cut a second one; stop if the tree is dirty and you would be creating a branch), same scope
decision.

One difference: **do not delete a stale `Plan/<task>/.review-findings.md`.** If it exists, it
is rework input — a tester or reviewer from a previous session wrote it.

## Dispatch

Dispatch the `p2p-dev` agent **once**, with:

- the resolved task folder path,
- the run scope you settled on,
- if `Plan/<task>/.review-findings.md` exists: an instruction to treat it as the work list and
  address every finding before anything else (the agent deletes the file once it has).

Wait for it to finish. Do **not** dispatch `p2p-tester` or `p2p-reviewer` — that is what the
other two commands are for.

## After it finishes — stop here

Report to the user:

1. Which subtasks were implemented, which remain.
2. Every file created or modified, grouped by area.
3. The `pytest` summary line and `ruff` result from the agent.
4. Whether a `.review-findings.md` was consumed and deleted, or none existed.
5. Any deviation from `design.md`.
6. The next step: `/p2p-task-test $1` in a fresh session.

**Do not** run the tester or reviewer, **do not** touch `Plan/MILESTONES.md` or
`Plan/ARCHITECTURE.md`, and **do not** commit anything.
