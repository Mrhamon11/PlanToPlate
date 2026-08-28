---
description: Dispatch only the p2p-reviewer stage of the PlanToPlate pipeline
argument-hint: <task-id, e.g. 05 or N2>
allowed-tools: Agent, Read, Bash, Glob, Grep
---

# PlanToPlate — reviewer stage only — `$1`

Run **only** the code-review stage for the task folder matching `$1` in `Plan/`. Implementation
and test verification were done in separate sessions.

## Setup

1. Resolve `$1` to a folder: `ls -d Plan/$1*`. If it does not resolve to exactly one folder,
   stop and ask.
2. Work out the task's branch name (`task/<folder-name-lowercased>`).
   - **On that branch already?** Good.
   - **Branch exists, you are elsewhere?** `git checkout` it.
   - **Branch does not exist?** Stop. Tell the user to run `/p2p-task-dev $1` first.
3. Do not create branches, do not commit, do not merge.

## Dispatch

Dispatch **exactly one** `p2p-reviewer` agent — never two, whatever the task. Give it the
resolved task folder path. It reads `Plan/ARCHITECTURE.md`, the task's plan files, and the diff
itself.

Wait for it to finish.

## After it finishes — stop here

**If the reviewer returned APPROVE:**

- Confirm `Plan/<task>/.review-findings.md` no longer exists (the reviewer deletes it on
  APPROVE; delete it yourself if it lingers).
- Tell the user plainly: **the reviewer approved task `$1`.** Include the non-blocking
  suggestions it raised and any noted deviation from `design.md`. Write no other files.
- Next step: the task is ready for the user's own review and approval. Point them at
  `/p2p-task $1`'s Handoff checklist (or just tell them what to verify and how to run it).

**If the reviewer returned REQUEST CHANGES:**

- The reviewer has appended the numbered blocking findings to
  `Plan/<task>/.review-findings.md`. Leave it in place — it is the handoff to the next dev
  session.
- Report to the user: the verdict, the blocking findings (ranked), and the non-blocking ones
  separately.
- Next step: `/p2p-task-dev $1` in a fresh session — the dev agent picks up
  `.review-findings.md` automatically.

Either way: **do not** touch `Plan/MILESTONES.md` or `Plan/ARCHITECTURE.md`, and **do not**
commit.
