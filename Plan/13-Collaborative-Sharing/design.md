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

## Carried-in findings

From the task-08 dev-test conversation (2026-09-07). These are the reason this task's spec
should be written **before** any more sharing UI is added piecemeal elsewhere.

1. **Rethink per-individual sharing itself.** Owner: "I don't really see a reason for anything
   other than recipes to be shared between individual users." The current model — any owned
   object (recipe, dish, book, list, plan) shareable one-user-at-a-time with a read grant and
   a child cascade — may be more machinery than the real use cases need. The spec should
   decide whether individual per-object sharing narrows to just `Recipe`, with everything else
   moving to the group model below.

2. **Household / family group.** The motivating case (two people, two accounts, one shared
   body of data) is better served by a **group** than by N pairwise shares. Concept: a user
   group where every ingredient / recipe / dish / meal plan / list owned by any member is
   automatically visible to every other member **and editable by them** — no per-object share
   action at all within the group. This is the headline feature of this task, not an add-on.
   Interacts with every open question already listed above (permission model, edit cascade,
   concurrency, revocation = leaving the group).

3. **Make-public UI discoverability.** Making an object `PUBLIC` is already possible via
   `_partials/_share_modal.html`'s "Everyone with an account" visibility radio (wired for
   recipe / dish / book / plan; not List, per D40). The owner flagged that it is hard to
   find. Whatever sharing UI this task lands should make the private / group / public choice
   obvious, and cover `List`.

4. **Sort / filter a list page by access type.** Users want to configure what a list page
   shows and order it by "mine / shared with me / public". Deferred here rather than bolted
   onto individual index pages, because the right grouping depends on whether the group model
   above replaces per-user shares.

5. **Narrowing access never cascades down — decide the rule for whatever model survives.**
   (Task 12 dev test, 2026-09-07 — owner request.) Granting access cascades down the owned
   graph; revoking / narrowing does not (D31, and [[11.11]]). Today this strands children on
   every path: recipe → sub-recipe, dish → recipes, book → recipes, plan → dish → recipes.
   Real incident: a demo dish reverted from `PUBLIC` left its component recipes `PUBLIC`, so a
   brand-new account saw them on its dashboard.
   - If per-object individual sharing narrows to `Recipe` + a group model (findings 1–2), the
     dish / book / plan legs **evaporate** — those objects go private-or-group-visible and
     leaving a group drops all access atomically. The spec should confirm this is the outcome
     and say so explicitly, so [[11.11]] can be closed for those legs.
   - What does **not** evaporate: reverting `PUBLIC` on any model that can still be made
     `PUBLIC` (finding 3 keeps the public option for recipe / dish / book / plan). The spec
     must decide — un-publish a container and either (a) its owned children stay `PUBLIC`
     (keep D31, document it as intended), or (b) offer the "also un-publish these children that
     aren't reachable from another public root: ☐ ☐" confirm step. This is the one piece of
     [[11.11]] that this task cannot avoid owning.

## Non-goals

- Real-time collaboration (presence, live cursors, CRDTs). Household scale, async edits.
- Public *write*. `PUBLIC` stays read-only for everyone but the owner.
