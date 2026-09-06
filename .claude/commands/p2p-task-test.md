---
description: Dispatch only the p2p-tester stage of the PlanToPlate pipeline
argument-hint: <task-id, e.g. 05 or N2>
allowed-tools: Agent, Read, Bash, Glob, Grep
---

# PlanToPlate — tester stage only — `$1`

Run **only** the test-verification stage for the task folder matching `$1` in `Plan/`. The
implementation was done in a separate `/p2p-task-dev` session.

## Setup

1. Resolve `$1` to a folder: `ls -d Plan/$1*`. If it does not resolve to exactly one folder,
   stop and ask.
2. Work out the task's branch name (`task/<folder-name-lowercased>`).
   - **On that branch already?** Good.
   - **Branch exists, you are elsewhere?** `git checkout` it.
   - **Branch does not exist?** Stop. The dev stage has not run — tell the user to run
     `/p2p-task-dev $1` first.
3. Do not create branches, do not commit, do not merge.

## Dispatch

Dispatch **one** `p2p-tester` agent. Give it the resolved task folder path and nothing else —
it reads `test-plan.md` and the `tasks.md` checkboxes itself, and reads application code only
if it hits a concrete problem. It gets one pass at fixing a broken test before handing back.

Wait for it to finish.

## After it finishes — stop here

**First, whatever the verdict: record every finding that will not be actioned in the next
dev pass.** Read `p2p-task.md`'s **Recording findings — nothing lives only in chat** section
and follow it. Weak-but-passing tests, coverage the tester flagged as thin but not
FAIL-worthy, deterministic-seed nits — each gets triaged into a file (`.review-findings.md`
for address-now, a `tasks.md` sub-note for later-this-task, a future task's `design.md` or
`Plan/BACKLOG.md` for later tasks). Make the obvious calls yourself; ask the user for any
you are unsure about.

**If the tester returned PASS:**

- The tester deletes `Plan/<task>/.review-findings.md` only if it raised nothing at all. If
  non-blocking observations remain in it, triage them per above, then delete the file
  yourself once every one has a permanent home. Confirm it is gone.
- Tell the user plainly: **the tester approved task `$1`.** Include the coverage table, note
  any test the tester fixed, and list each non-blocking observation with its disposition.
- Next step: `/p2p-task-review $1` in a fresh session.

**If the tester returned FAIL:**

- The tester has written the numbered work list to `Plan/<task>/.review-findings.md`. Leave it
  in place — it is the handoff to the next dev session.
- Report to the user: the verdict, the `pytest` summary, the coverage gaps, the weak tests,
  and the disposition of any non-blocking observations.
- Next step: `/p2p-task-dev $1` in a fresh session — the dev agent will pick up
  `.review-findings.md` automatically.

Either way: **do not** touch `Plan/MILESTONES.md` or `Plan/ARCHITECTURE.md`, **do not** run the
reviewer, and **do not** commit. (Recording findings into `tasks.md` / `design.md` /
`Plan/BACKLOG.md` is expected and does not count as a design change.)
