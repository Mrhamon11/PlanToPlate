# N1 — Images & Camera · Design

> **Read [`../MILESTONES.md`](../MILESTONES.md) before starting.** Update it when this task completes.
> Siblings: [`tasks.md`](tasks.md) · [`test-plan.md`](test-plan.md)
>
> *Nice-to-have. Lighter detail than the MVP tasks — expect to refine this design once the MVP
> is real and you know how people actually use the app.*

## Goal

Images on Recipes, Dishes, Lists, Ingredients, and RecipeBooks, by upload or straight from the
phone camera.

**Depends on:** 05 (and 10 for the security posture).
**Enables:** N2, N3.

## Model

One polymorphic-by-explicit-FK attachment model, mirroring `ListItem`'s approach from task 07
— explicit nullable FKs rather than a generic relation, for real constraints and cheap queries.

```python
class Image(OwnedModel):
    file = models.ImageField(upload_to=upload_path)
    thumbnail = models.ImageField(...)
    caption = models.CharField(max_length=200, blank=True)
    width, height, byte_size
    is_primary = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    recipe / dish / list / ingredient / recipe_book   # nullable FKs, exactly one set
```

`upload_path` is `images/<owner_id>/<uuid4>.<ext>` — **the uploaded filename is never used on
disk.** A user-supplied filename is a path-traversal vector and a collision source; a UUID is
neither.

`is_primary` picks the card image. A partial unique constraint enforces one primary per parent.

## Upload pipeline

Every upload, without exception:

1. Size cap (10 MB) enforced before reading the whole file.
2. **Verify the content, not the extension.** `Pillow.Image.open()` + `verify()`. A `.jpg` that
   is actually an HTML file is a stored-XSS payload if it is ever served with a sniffed type.
3. Allowlist: JPEG, PNG, WebP, HEIC. **SVG is rejected** — it is a scriptable document, not an
   image, and serving user SVG from the app origin is XSS.
4. Reject decompression bombs: cap the decoded pixel count (`Image.MAX_IMAGE_PIXELS`). A 10 KB
   PNG can decode to gigabytes.
5. **Re-encode** to a normalised JPEG/WebP. This strips any polyglot payload and any EXIF —
   including GPS coordinates, which on a photo of your own kitchen is a home address.
6. Resize: max 2048px on the long edge, plus a 400px thumbnail.
7. Store with `Content-Type` set explicitly and `X-Content-Type-Options: nosniff` (task 10).

Processing runs synchronously — a resize is fast enough at this scale, and `django-q2` is
reserved for N2's genuinely slow work.

## Storage

`MEDIA_ROOT` on a persistent volume, served by Caddy with `nosniff` and no `Content-Disposition:
inline` for anything unexpected. A `django-storages` seam is kept so S3 is a settings change,
per the cloud-portability requirement.

**Media must be in the backup story from task 10** — task 10 backs up the database; this task
adds the media sync. A restore that brings back recipes without their photos is a half restore.

## Camera capture

Mostly free on mobile web:

```html
<input type="file" accept="image/*" capture="environment">
```

That opens the rear camera directly on iOS and Android. A `getUserMedia` in-page preview is
explicitly **out of scope** — it is materially more code, needs a permissions story, and the
native picker is better than anything we would build. Desktop degrades to a normal file picker.

## UI

- Drag-and-drop upload zone with a tap-to-select fallback (task 02's touch-parity rule).
- Client-side downscale before upload via canvas, so a 12 MP phone photo does not need a
  12 MP upload on kitchen wifi. The server re-processes regardless — client-side work is a
  convenience, never a trust boundary.
- Gallery with reorder, set-primary, caption, and delete.
- Upload progress and a clear error when a file is rejected, naming the reason.
- `loading="lazy"` and explicit dimensions to avoid layout shift.

## Edge cases

- HEIC from iPhones needs `pillow-heif`; if unavailable, reject with a clear message rather
  than a 500.
- Deleting an object deletes its images and the files on disk (a `post_delete` signal), or the
  volume fills with orphans over time.
- Replacing a primary image demotes the old one atomically.
- An image whose parent is shared inherits the parent's visibility — an image is not
  independently shareable.
- Animated GIF: take the first frame.
- Very tall or wide panoramas: cap both dimensions, not just the long edge.

## Security notes

This is one of the two genuinely dangerous features in the backlog (`MILESTONES.md` §6.3).

- Content-based type validation, never extension-based.
- SVG rejected outright.
- Re-encode everything — it is the single most effective defence, since it destroys polyglots.
- Decompression-bomb caps.
- UUID filenames; the user's filename is stored as a display label only, escaped.
- Serve media with `nosniff`; ideally from a separate hostname so that even a bypass lands
  outside the app origin. Document it as the recommended production setup.
- Strip EXIF, including GPS.
- Per-user storage quota (500 MB default) so one user cannot fill the disk and take SQLite
  down with it.
- Media access respects the parent's visibility — a private recipe's photo must not be
  readable by URL guess. Serve through a permission-checking view, or accept UUID-obscurity
  and **document the trade-off explicitly** rather than leaving it implicit.
