# 03 — Ownership & Sharing · Subtasks

> Design: [`design.md`](design.md) · Tests: [`test-plan.md`](test-plan.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

There is no domain model yet, so subtasks 03.1–03.8 are exercised against a throwaway
`core.tests.models.DummyOwned` registered only under test settings. Building the machinery
against a stand-in keeps this task independent of task 04.

- [ ] **03.1 — `Visibility` choices and `OwnedModel`**
  The abstract base from the design, including the owner-XOR-system check constraint.
  *Files:* `core/models.py`
  *Done when:* a concrete subclass migrates cleanly and the constraint rejects a system object
  that has an owner.

- [ ] **03.2 — `OwnedQuerySet` / `OwnedManager`**
  `visible_to()` and `editable_by()`, including the anonymous-user `.none()` path and `.distinct()`.
  *Files:* `core/managers.py`
  *Done when:* the visibility matrix tests pass.

- [ ] **03.3 — Permission classes**
  `IsOwnerOrReadOnly`, `IsOwner`, `CanCopy`.
  *Files:* `core/permissions.py`

- [ ] **03.4 — Dependency-graph traversal helper**
  `walk_dependencies(obj)` — transitive, cycle-guarded, depth-capped. Shared by the sharing
  cascade and the copy service, and later by the recipe flattener.
  *Files:* `core/services/graph.py`
  *Done when:* a deliberately cyclic fixture terminates and raises `CycleError`.

- [ ] **03.5 — Sharing service**
  `share`, `unshare`, `set_visibility`, with the child cascade and the refuse-with-a-named-
  blocker behaviour.
  *Files:* `core/services/sharing.py`
  *Done when:* sharing a container grants its children, and an ungrantable child refuses the
  whole share with a message naming it.

- [ ] **03.6 — Copy service**
  `copy_object` — deep, atomic, always private, `copied_from` set, stats not copied.
  *Files:* `core/services/copying.py`
  *Done when:* copying a two-level structure produces a fully independent tree and editing the
  original leaves the copy untouched.

- [ ] **03.7 — Base serializers**
  `OwnedSerializer` with `owner`, `is_system`, `shared_with`, and `copied_from` all read-only;
  `owner` injected from `request.user`.
  *Files:* `core/serializers.py`
  *Done when:* a request that posts `owner` cannot change it.

- [ ] **03.8 — `OwnedViewSetMixin`**
  `get_queryset()` via `visible_to`, the `share` / `unshare` / `copy` / `shares` actions, and
  the `mine` / `shared_with_me` / `public` filters.
  *Files:* `core/viewsets.py`, `core/filters.py`
  *Done when:* the dummy model's endpoints pass the full IDOR matrix.

- [ ] **03.9 — View mixins for HTML views**
  Fill in `OwnedObjectMixin` (stubbed in task 02) so template views get the same queryset
  filtering as the API. **The HTML views must not have a second, weaker path to the data.**
  *Files:* `core/mixins.py`

- [ ] **03.10 — Share modal and ownership badges**
  `_share_modal.html`, `_ownership_badge.html`, `_copy_button.html`, and the CSS for them.
  *Files:* `templates/_partials/*.html`, `static/css/components.css`

- [ ] **03.11 — Documentation for future tasks**
  A short `core/README.md`: how to make a new model owned, and the checklist of things that
  must be wired (manager, serializer base, viewset mixin, `share_dependencies`,
  `copy_children`).
  *Files:* `core/README.md`
  *Done when:* tasks 04–08 can follow it without rereading this design.

- [ ] **03.12 — Update the living document**
  Task 03 → AWAITING APPROVAL. Record any refinement to the sharing rules.
  *Files:* `Plan/MILESTONES.md`
