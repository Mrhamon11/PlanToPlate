# 03 — Ownership & Sharing · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

**This is the largest and most important test suite in the project.** Everything else assumes
this layer is correct. A gap here is a data leak in every feature built on top of it, so the
bar is: for each rule in the design, there is a test that fails when that rule is removed.

Standard fixtures: `alice` (owner), `bob` (shared-with), `carol` (unrelated), `admin`.

## Model — `core/tests/test_owned_model.py`

| Test | Asserts |
|---|---|
| `test_defaults_to_private` | New objects are `PRIVATE` with an empty `shared_with`. |
| `test_owner_required_for_non_system` | Saving a non-system object with no owner violates the constraint. |
| `test_system_object_must_have_no_owner` | The other half of the XOR. |
| `test_notes_field_present` | Every owned model has `notes` — a requirement that is easy to forget on model #6. |
| `test_copied_from_set_null_on_source_delete` | Deleting the original leaves the copy alive with `copied_from` NULL. |
| `test_owner_cascade_deletes_objects` | Deleting a user deletes what they own. |

## The visibility matrix — `core/tests/test_visibility.py`

The core table. Parametrized across `(visibility, viewer)`.

| Object state | alice (owner) | bob (shared) | carol (unrelated) |
|---|---|---|---|
| PRIVATE | visible | **not visible** | **not visible** |
| SHARED, bob granted | visible | visible | **not visible** |
| PUBLIC | visible | visible | visible |
| system | visible | visible | visible |

| Test | Asserts |
|---|---|
| `test_visibility_matrix[...]` | Every cell above. |
| `test_anonymous_gets_empty_queryset` | `.visible_to(AnonymousUser())` returns `.none()`, not an exception — a missing `@login_required` degrades to empty, not to a leak. |
| `test_visible_to_is_distinct` | An object shared with three users appears **once**. Without `.distinct()` the M2M join duplicates it. |
| `test_editable_by_owner_only` | Shared and public viewers are excluded from `editable_by`. |
| `test_editable_by_excludes_system` | Even a superuser cannot get a system object through `editable_by`. |
| `test_visible_to_query_count` | The filter is one query, and does not degrade to N+1 on a list of 50. |

## Permissions — `core/tests/test_permissions.py`

| Test | Asserts |
|---|---|
| `test_owner_can_write` | |
| `test_shared_user_cannot_write` | PUT/PATCH/DELETE denied on an object shared *to* them. |
| `test_public_object_not_writable_by_others` | Public means readable, never writable. |
| `test_system_object_not_writable_by_anyone` | Including staff, through the API. |
| `test_unrelated_user_gets_404_not_403` | **A private object must 404.** A 403 confirms the object exists and turns the ID space into an enumeration oracle. |

## IDOR matrix — `core/tests/test_idor.py`

For the dummy resource, every verb × every relationship. This is the suite that exists to catch
the single most likely serious bug in the project.

| Test | Asserts |
|---|---|
| `test_cannot_retrieve_others_private[GET]` | 404. |
| `test_cannot_update_others_object[PUT,PATCH]` | 404/403; the row is unchanged afterward. |
| `test_cannot_delete_others_object[DELETE]` | 404/403; the row still exists afterward. |
| `test_list_excludes_others_private` | Carol's list response contains none of Alice's IDs. |
| `test_cannot_set_owner_on_create` | Posting `owner: bob.id` still creates it owned by the requester. |
| `test_cannot_set_is_system_on_create` | Ignored. |
| `test_cannot_inject_shared_with_on_update` | `shared_with` is read-only through the serializer; grants happen only via the share endpoint. |
| `test_filters_cannot_bypass_visibility` | `?mine=`, `?public=`, ordering, and search params are each attempted as a bypass and each still returns only visible rows. |

## Sharing service — `core/tests/test_sharing.py`

| Test | Asserts |
|---|---|
| `test_owner_can_share` | Bob gains visibility. |
| `test_non_owner_cannot_share` | Bob, holding a share, sharing to Carol → `PermissionDenied`. **The core anti-reshare rule.** |
| `test_cannot_share_system_object` | |
| `test_share_with_self_is_noop` | No error, no row. |
| `test_share_cascades_to_children` | Sharing a container grants read on its children, transitively to the second level. |
| `test_share_refused_when_child_not_grantable` | A child owned by someone else and invisible to the target refuses the whole share, and the error **names the blocking object**. A vague failure here is unfixable by the user. |
| `test_share_succeeds_when_foreign_child_already_visible` | The same case, but the child is already public → the share proceeds. |
| `test_unshare_removes_access` | |
| `test_unshare_does_not_cascade` | Child grants survive, because they may be load-bearing for a different object. |
| `test_public_to_private_preserves_explicit_grants` | Dropping PUBLIC leaves `shared_with` intact. |
| `test_shares_list_visible_to_owner_only` | A non-owner requesting `/shares/` gets 403/404. The audience list is itself sensitive. |
| `test_share_cascade_terminates_on_cycle` | A cyclic dependency graph does not hang. |

## Copy service — `core/tests/test_copying.py`

| Test | Asserts |
|---|---|
| `test_copy_creates_independent_object` | New PK, `owner` is the actor. |
| `test_copy_is_always_private` | Copying a PUBLIC object yields a PRIVATE one. Inheriting the visibility would silently republish someone else's work. |
| `test_copy_sets_copied_from` | Provenance recorded. |
| `test_copy_does_not_carry_shares` | `shared_with` is empty on the copy. |
| `test_cannot_copy_invisible_object` | Carol copying Alice's private object → 404. |
| `test_can_copy_shared_object` | |
| `test_can_copy_system_object` | And the copy is fully editable — the seeded-ingredient use case. |
| `test_deep_copy_copies_children` | A two-level structure is copied whole. |
| `test_editing_original_does_not_affect_copy` | The independence guarantee, tested from both directions. |
| `test_deleting_original_does_not_affect_copy` | |
| `test_copy_does_not_carry_user_stats` | The copy starts at `times_made=0` with no rating. |
| `test_copy_is_atomic` | With a child save patched to fail, **no** partial objects remain. |
| `test_copy_respects_depth_limit` | Beyond the cap, raises rather than recursing. |
| `test_copy_terminates_on_cycle` | |

## Serializers — `core/tests/test_serializers.py`

| Test | Asserts |
|---|---|
| `test_readonly_fields_enforced` | `owner`, `is_system`, `shared_with`, `copied_from` all reject writes. |
| `test_owner_injected_from_request` | |
| `test_nested_children_filtered_by_visibility` | A serialized parent does **not** expand a child the requester cannot see. The relation-leak case. |

## HTML views — `core/tests/test_view_mixins.py`

| Test | Asserts |
|---|---|
| `test_html_list_view_filters_by_visibility` | |
| `test_html_detail_view_404s_on_invisible` | |
| `test_html_and_api_agree_on_visibility` | The same user, the same object, both paths — identical verdict. Guards against the HTML side growing a weaker query than the API. |

## Regression guard — `core/tests/test_conventions.py`

| Test | Asserts |
|---|---|
| `test_all_owned_viewsets_use_visible_to` | Introspect every registered viewset whose model subclasses `OwnedModel`; its `get_queryset()` must route through `visible_to`. **This is the test that keeps task 03's guarantee true in tasks 04–08**, when someone adds a viewset in a hurry. |
| `test_all_owned_models_declare_hooks` | Every `OwnedModel` subclass with relations defines `share_dependencies()` and `copy_children()`. |

## Definition of Done

- [ ] Every test above exists and passes; the visibility matrix is exhaustive.
- [ ] `ruff` clean; full suite green.
- [ ] A private object returns **404**, never 403, to a user who cannot see it.
- [ ] A non-owner cannot share, under any endpoint, for any model.
- [ ] Copies are independent, private, atomic, and carry no stats.
- [ ] The convention tests in `test_conventions.py` pass — they are what protects later tasks.
- [ ] `core/README.md` exists and is accurate enough for task 04 to follow unaided.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
