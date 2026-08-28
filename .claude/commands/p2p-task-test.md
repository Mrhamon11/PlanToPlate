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

**If the tester returned PASS:**

- Confirm `Plan/<task>/.review-findings.md` no longer exists (the tester deletes it on PASS;
  delete it yourself if it lingers).
- Tell the user plainly: **the tester approved task `$1`.** Include the coverage table and note
  any test the tester fixed. Write no other files.
- Next step: `/p2p-task-review $1` in a fresh session.

**If the tester returned FAIL:**

- The tester has written the numbered work list to `Plan/<task>/.review-findings.md`. Leave it
  in place — it is the handoff to the next dev session.
- Report to the user: the verdict, the `pytest` summary, the coverage gaps, and the weak tests.
- Next step: `/p2p-task-dev $1` in a fresh session — the dev agent will pick up
  `.review-findings.md` automatically.

Either way: **do not** touch `Plan/MILESTONES.md` or `Plan/ARCHITECTURE.md`, **do not** run the
reviewer, and **do not** commit.
