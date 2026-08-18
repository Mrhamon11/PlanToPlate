# N3 — Social Feed · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)
>
> *Nice-to-have. Lighter detail — this design is the most likely of the four to change once the
> MVP has real users, because what people actually want to share only becomes clear then.*

## Goal

A feed where users post text, images, and database objects to a chosen audience, and readers
can copy shared objects straight from the post.

**Depends on:** 06, N1.

## Models

```python
class Post(OwnedModel):
    body = models.TextField(blank=True)
    audience = models.CharField(choices=Audience.choices)     # PUBLIC | SPECIFIC
    # `shared_with` from OwnedModel carries the SPECIFIC audience — no second mechanism

class PostAttachment(models.Model):
    post = FK(Post, related_name="attachments")
    position = PositiveIntegerField()
    image / recipe / dish / ingredient / recipe_book          # nullable FKs, exactly one set
```

**Post reuses `OwnedModel`'s `visibility` and `shared_with` rather than inventing a parallel
audience system.** The audience *is* the visibility, so the whole task 03 apparatus — the
`visible_to` filter, the permission classes, the tests — applies unchanged. A second, bespoke
audience mechanism would be a second place for the visibility logic to be wrong.

Attachments follow the same explicit-nullable-FK pattern as `ListItem` (task 07) and `Image`
(N1), for the third time. That consistency is deliberate: one pattern, understood once.

## The visibility rule that matters

Posting an object **grants read on it to the post's audience** — implemented by calling task
03's existing `share()` service, cascade and all, not by writing new logic.

Consequences that must be made explicit in the UI:

- Posting a private recipe to `PUBLIC` makes that recipe public. The compose screen must say
  so plainly before posting, because it is a one-way disclosure the user may not expect.
- If a dependency cannot be granted (a sub-recipe you do not own), task 03's cascade refuses
  the share — and therefore refuses the post, naming the blocker.
- **Deleting a post does not revoke the grant.** People may already have copied it, and
  silently un-sharing would break their view of an object they were legitimately given. If
  revocation is wanted it is an explicit, separate action on the object itself.

That last point is a real decision with a real trade-off, and it must be recorded in
`MILESTONES.md` rather than left to be rediscovered.

## Feed

`GET /api/posts/feed/` → `Post.objects.visible_to(user)`, newest first, cursor-paginated.

Cursor rather than offset pagination: a feed that grows while you scroll produces duplicate and
skipped rows under offset pagination.

`select_related`/`prefetch_related` the attachment graph. A feed is the most N+1-prone screen
in any application.

## Copy from the feed

The requirement: a reader can copy an attached object directly from the post. This is task 03's
`copy_object` on a button — no new logic, and the "you may copy what you can see" rule already
holds because the post granted visibility.

## UI

- **Feed** — cards showing author, time, body, attachment previews, and a copy button per
  database object. Infinite scroll via HTMX, with a working "load more" fallback for
  no-JavaScript and for accessibility.
- **Compose** — body text, attachment picker (visibility-filtered), audience selector, and
  **an explicit warning naming exactly which objects will become visible to whom.**
- **Post detail** — permalink, full attachments.
- **Profile feed** — one user's posts, filtered by what you can see.

## Deliberately out of scope

Comments, likes, follows, and notifications. The requirement asks for a page showing what
people are sharing, not a social network. Each of those brings moderation, notification
delivery, and read-state problems that are disproportionate for 20 users who mostly know each
other. Recorded here so the omission is a decision rather than an oversight.

## Edge cases

- A post whose attached object is later deleted: `SET_NULL`, rendered as "(no longer
  available)". The post survives.
- Posting an object already public: no-op on visibility.
- Empty post (no body, no attachments): rejected.
- Audience changed after posting: re-runs the share for newly added users. **Removing users
  does not revoke** — same rationale as deletion.
- A post attaching an object you can see but do not own: allowed only if you could share it,
  which per task 03 you cannot. So: you may post only your own objects, or public ones. The UI
  must filter the picker accordingly rather than failing at submit.
- A very long body: capped at 5000 characters.

## Security notes

- Everything routes through task 03. **No new visibility logic is written in this task** — if
  it seems necessary, the design is wrong.
- The attachment picker filters by `editable_by` (you may post what you own) plus already-public
  objects, not merely `visible_to`.
- The compose warning is a security control, not decoration: it is what prevents accidental
  disclosure of a private recipe.
- Body text is escaped; no HTML rendering, or an allowlist sanitiser if markdown is added.
- Feed pagination must not leak the existence of invisible posts through cursor gaps or counts.
- Rate limit posting (20/hour) as basic spam control.
