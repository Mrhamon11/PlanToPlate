# 13 — Collaborative Sharing · Design (DRAFT — spec required before implementation)

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.**
> This file is a **scope sketch**, not an implementation-ready design. It was captured from a
> task-07 dev-test conversation (2026-09-05). Do not start coding from it — write the real
> `design.md` and `test-plan.md` first, resolving every open question below.

## Goal

Today a share grants **read only**: a recipient can view a shared recipe / dish / book / list,
or copy it to modify (the copy is theirs, the original is untouched). That behaviour stays — it
is one of the sharing modes, not a thing to remove.

Add a second mode: a share that also grants **edit**. The motivating use case is a household —
two people who both want to create and edit the same recipes, dishes, books, and shopping
lists, not maintain divergent copies.

**Depends on:** 03-Ownership-And-Sharing (the visibility keystone, `shared_with`,
`IsOwnerOrReadOnly`, the sharing/copy cascade services).

## What exists to build on (task 03)

- `OwnedModel` + `.visible_to(user)` — the single visibility primitive every queryset uses.
- `shared_with` M2M (per-user grants) and `visibility = PRIVATE | SHARED | PUBLIC`.
- `IsOwnerOrReadOnly` — object-level write permission: owner writes, everyone else read-only.
- `core/services/sharing.py` — grant/revoke with a child cascade and a cascade-refusal check.
- `_partials/_share_modal.html` — the share UI (recipes/dishes/books use it; lists do **not**
  yet — see [[11.26]]).

## Open questions the spec must resolve

1. **Permission model.** A new per-user grant level (`VIEW` / `EDIT`) on the share, vs. a
   separate `editors` M2M alongside `shared_with`. How does `IsOwnerOrReadOnly` become
   "owner-or-editor writes"? Does a new `IsOwnerOrEditorOrReadOnly` replace it everywhere, or
   sit beside it?
2. **Concurrent edits.** Two people ticking the same shopping list at once — the exact case
   task 07 deliberately punted on (`design.md`, "Edge cases": "a shared shopping list two
   people both tick is a different feature with concurrency questions this app does not need").
   Last-write-wins? Per-field? Optimistic concurrency with a version column? The shopping-list
   check-off flow is the highest-contention surface and should drive this decision.
3. **Cascade.** Sharing a book/dish for *edit* — do the child recipes become editable too, or
   only viewable? Task 03's grant cascade shares read access down the graph; an edit cascade
   is a bigger blast radius (an editor of one dish could rewrite a recipe used by other dishes
   they were never given).
4. **`copied_from` interaction.** If you can edit the original, the "copy to modify" flow is
   partly redundant — but not entirely (you may still want a private fork). Keep both; define
   when each is offered.
5. **Ownership transfer / co-ownership.** Is an editor still not an owner (can't delete, can't
   re-share, can't change visibility)? Almost certainly yes — keep delete/share/visibility
   owner-only — but state it.
6. **Audit / attribution.** Does an edit by a non-owner get recorded (who changed what)? At
   10–20 household users, probably a light `updated_by` is enough; decide.
7. **Revocation.** Downgrading `EDIT` → `VIEW` or revoking entirely — interacts with [[11.11]]
   (revoke does not currently cascade down the sub-recipe DAG) and [[11.19]] (a recipient
   can't remove a shared object from their own view).

## Surfaces to touch (once spec'd)

- `core/models.py` / a sharing model — the grant-level field or `editors` relation + migration.
- `core/permissions.py` — the owner-or-editor write permission.
- `core/services/sharing.py` — grant/revoke at a level; the edit-cascade decision.
- Every `OwnedViewSetMixin` viewset and `OwnedObjectMixin` HTML view — they currently trust
  `IsOwnerOrReadOnly`; the swap must be single-point, not per-view (CLAUDE.md §6).
- `_partials/_share_modal.html` — a VIEW/EDIT toggle per recipient.
- Task 07's shopping-list check-off / add / reorder / clear views — currently hard-gated to
  the owner via `_owned_list`; an editor must pass. This is where concurrency shows up.

## Non-goals

- Real-time collaboration (presence, live cursors, CRDTs). Household scale, async edits.
- Public *write*. `PUBLIC` stays read-only for everyone but the owner.
