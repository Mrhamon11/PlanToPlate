# N3 — Social Feed · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Models — `social/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_post_is_owned` | |
| `test_attachment_requires_exactly_one_target` | |
| `test_empty_post_rejected` | No body and no attachments. |
| `test_body_length_capped` | |
| `test_attachments_ordered` | |
| `test_deleted_attachment_target_nulls` | The post survives, rendering "(no longer available)". |

## Sharing behaviour — `social/tests/test_sharing.py`

The heart of the task, and all of it delegated to task 03.

| Test | Asserts |
|---|---|
| `test_posting_grants_read_to_audience` | |
| `test_posting_public_makes_object_public` | |
| `test_posting_cascades_to_dependencies` | Task 03's cascade, unchanged. |
| `test_post_refused_when_dependency_not_grantable` | Named blocker. |
| `test_deleting_post_does_not_revoke` | Pins the documented decision, so a future change is deliberate. |
| `test_changing_audience_grants_new_users` | |
| `test_removing_audience_member_does_not_revoke` | Same rationale. |
| `test_no_new_visibility_logic` | Greps the app for `Q(owner=` / `visibility=` filters outside the task 03 imports; the app must reuse, not reimplement. |

## Feed — `social/tests/test_feed.py`

| Test | Asserts |
|---|---|
| `test_feed_shows_public_posts` | |
| `test_feed_shows_posts_shared_with_me` | |
| `test_feed_excludes_private_posts` | |
| `test_feed_ordered_newest_first` | |
| `test_cursor_pagination_stable_under_insert` | A new post mid-scroll causes no duplicate or skipped row — the reason offset pagination was rejected. |
| `test_feed_query_count_flat` | Independent of page size. The most N+1-prone screen in any app. |
| `test_pagination_does_not_leak_invisible_posts` | No cursor gaps or counts revealing hidden rows. |

## Copy — `social/tests/test_copy.py`

| Test | Asserts |
|---|---|
| `test_copy_attached_recipe_from_feed` | |
| `test_copied_object_is_independent` | Task 03's guarantee, through this path. |
| `test_cannot_copy_from_invisible_post` | |

## Security — `social/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_post_idor_matrix` | |
| `test_cannot_attach_object_you_cannot_post` | The picker rule enforced server-side, not only in the UI. |
| `test_cannot_attach_others_private_object` | |
| `test_body_is_escaped` | |
| `test_post_rate_limited` | |
| `test_cannot_edit_others_post` | |

## UI — `social/tests/test_views.py`

| Test | Asserts |
|---|---|
| `test_feed_renders` | |
| `test_compose_warning_names_objects_and_audience` | The warning is a **security control**, not decoration — it is what prevents accidental disclosure of a private recipe. |
| `test_attachment_picker_filtered` | Only postable objects offered. |
| `test_infinite_scroll_has_load_more_fallback` | Works without JavaScript. |
| `test_copy_button_present_on_db_attachments` | |
| `test_deleted_attachment_renders_placeholder` | No 500. |

## Manual verification

1. Post a private recipe to PUBLIC; confirm the warning names it, then confirm another user
   can see and copy it.
2. Attempt to post a dish containing a recipe you do not own; confirm refusal names the blocker.
3. Scroll a feed of 50 posts on a phone; confirm no duplicates and no jumping.

## Definition of Done

- [ ] Every test above exists and passes.
- [ ] **No visibility logic is reimplemented in this app** — `test_no_new_visibility_logic` passes.
- [ ] The compose warning names the exact objects and audience.
- [ ] Feed pagination is cursor-based and leak-free.
- [ ] The no-revoke-on-delete decision is recorded in `MILESTONES.md`.
- [ ] All three manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
