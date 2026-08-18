# N1 — Images & Camera · Test Plan

> Design: [`design.md`](design.md) · Subtasks: [`tasks.md`](tasks.md) · Living doc: [`../MILESTONES.md`](../MILESTONES.md)

## Upload security — `images/tests/test_upload_security.py`

The core of this task. Fixtures live in `images/tests/fixtures/malicious/`.

| Test | Asserts |
|---|---|
| `test_rejects_svg` | Even renamed `.png`. SVG is a scriptable document, not an image. |
| `test_rejects_html_disguised_as_jpg` | Content-based validation, not extension-based. |
| `test_rejects_php_polyglot` | |
| `test_rejects_decompression_bomb` | A small PNG decoding to gigabytes is refused. |
| `test_rejects_oversized_file` | Refused before the whole file is read. |
| `test_rejects_zero_byte_file` | |
| `test_rejects_truncated_image` | |
| `test_accepts_valid_jpeg_png_webp` | |
| `test_filename_never_used_on_disk` | A filename of `../../etc/passwd` is stored as a UUID. |
| `test_original_filename_escaped_in_display` | |
| `test_exif_stripped` | Including **GPS** — a kitchen photo otherwise carries a home address. |
| `test_reencoded_output_differs_from_input` | Re-encoding is what destroys polyglot payloads. |
| `test_quota_enforced` | Over quota → refused with a clear message. |

## Processing — `images/tests/test_processing.py`

| Test | Asserts |
|---|---|
| `test_resizes_to_max_dimension` | |
| `test_thumbnail_generated` | |
| `test_aspect_ratio_preserved` | |
| `test_panorama_capped_both_dimensions` | |
| `test_animated_gif_first_frame` | |
| `test_dimensions_and_size_recorded` | |

## Model — `images/tests/test_models.py`

| Test | Asserts |
|---|---|
| `test_exactly_one_parent_required` | Zero or two parents → constraint error. |
| `test_one_primary_per_parent` | |
| `test_setting_primary_demotes_previous` | Atomically. |
| `test_deleting_parent_deletes_images` | |
| `test_deleting_image_removes_file` | No orphans on disk. |

## Access control — `images/tests/test_security.py`

| Test | Asserts |
|---|---|
| `test_image_inherits_parent_visibility` | A private recipe's image is not listed to others. |
| `test_cannot_attach_to_others_object` | |
| `test_cannot_delete_others_image` | |
| `test_media_url_access_documented` | Whichever of permission-checked serving or UUID-obscurity was chosen, the test pins it — so the trade-off is a recorded decision rather than an accident. |

## API and UI — `images/tests/test_api.py`, `test_views.py`

| Test | Asserts |
|---|---|
| `test_upload_returns_image` | |
| `test_reorder` · `test_set_primary` · `test_caption` · `test_delete` | |
| `test_upload_error_names_reason` | Not a generic failure. |
| `test_camera_input_has_capture_attribute` | The one-line mobile camera feature. |
| `test_gallery_lazy_loads` | `loading="lazy"` and explicit dimensions. |
| `test_upload_has_tap_fallback` | Not drag-only — task 02's touch-parity rule. |

## Manual verification

1. Upload a photo from a phone camera directly into a recipe.
2. Upload a GPS-tagged photo and confirm with `exiftool` that the stored file has no location.
3. Attempt to upload an SVG and an HTML file renamed to `.jpg` — both refused with clear reasons.
4. Run task 10's backup and restore; confirm images come back with the recipes.

## Definition of Done

- [ ] Every test above exists and passes; every malicious fixture is rejected.
- [ ] All images are re-encoded and EXIF-stripped.
- [ ] SVG is rejected under every extension.
- [ ] Uploaded filenames never reach the filesystem.
- [ ] Per-user quota enforced.
- [ ] Media is included in backups and verified by a restore.
- [ ] The media access-control trade-off is documented in `MILESTONES.md`.
- [ ] All four manual verifications performed and reported.
- [ ] Subtasks ticked; `../MILESTONES.md` updated.
