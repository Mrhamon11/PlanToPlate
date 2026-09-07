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

**First, whatever the verdict: record every non-blocking finding.** Read `p2p-task.md`'s
**Recording findings — nothing lives only in chat** section and follow it. Triage each
non-blocking finding the reviewer raised into its file (`.review-findings.md` for
address-now, a `tasks.md` sub-note for later-this-task, a future task's `design.md` or
`Plan/BACKLOG.md` for later tasks). Make the obvious calls yourself; ask the user with a
short questionnaire for any you are unsure about. A non-blocking finding that only appears
in your chat reply is a bug in this command — the next session will never see it.

**If the reviewer returned APPROVE:**

- The reviewer deletes `Plan/<task>/.review-findings.md` only if it raised no findings at
  all. If non-blocking findings remain in it, triage them per above, then delete the file
  yourself once every finding has a permanent home. Confirm it is gone.
- Tell the user plainly: **the reviewer approved task `$1`.** List each non-blocking finding
  with the disposition you gave it, and any noted deviation from `design.md`.
- Next step: the task is ready for the user's own review and approval. Point them at
  `/p2p-task $1`'s Handoff checklist (or just tell them what to verify and how to run it).

**If the reviewer returned REQUEST CHANGES:**

- The reviewer has appended the numbered blocking findings to
  `Plan/<task>/.review-findings.md`. Leave it in place — it is the handoff to the next dev
  session. Add the address-now non-blocking findings to it under their own heading.
- Report to the user: the verdict, the blocking findings (ranked), and the non-blocking ones
  with their dispositions.
- Next step: `/p2p-task-dev $1` in a fresh session — the dev agent picks up
  `.review-findings.md` automatically.

Either way: **do not** touch `Plan/MILESTONES.md` or `Plan/ARCHITECTURE.md`, and **do not**
commit. (Recording findings into `tasks.md` / `design.md` / `Plan/BACKLOG.md` is expected
and does not count as a design change.)
