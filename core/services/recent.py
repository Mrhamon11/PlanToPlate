"""Recently-viewed telemetry (``Plan/12-Home-Dashboard/design.md``, "Recently viewed").

Two entry points:

- ``record_view(user, obj)`` — called from the recipe / dish / book **detail** views (through
  ``core.mixins.RecordsRecentView``). Upserts one ``RecentView`` row, prunes the user back to
  ``RECENT_VIEW_LIMIT`` rows, and **swallows every failure**: recording that someone looked at
  a recipe must never 500 the recipe page (a locked database is the plausible cause).
- ``recent_for(user, limit)`` — called from ``core.services.dashboard``. Returns the live
  objects, newest first, each re-resolved through its own model's ``.visible_to(user)`` so a
  row whose object has since been deleted or un-shared simply drops out. Resolves the generic
  references with **one query per content type**, never one per row.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from core.models import RecentView

logger = logging.getLogger(__name__)

#: Rows kept per user. Pruned on write so the dashboard's read path carries no housekeeping
#: (``design.md``, "Capped per user").
RECENT_VIEW_LIMIT = 50

#: How many recently-viewed objects a single read (the dashboard panel) asks for — a panel is
#: a glance, not the full 50-row history. Shared with ``core.services.dashboard`` so the two
#: layers never drift apart.
RECENT_LIMIT = 8


def record_view(user: object, obj: object) -> None:
    """Record that ``user`` just opened ``obj``'s detail page.

    Bumps the single ``(user, content_type, object_id)`` row's ``viewed_at`` (creating it the
    first time), then prunes the user's rows beyond ``RECENT_VIEW_LIMIT``. Any exception —
    most plausibly ``OperationalError: database is locked`` — is logged and swallowed: the
    detail page still renders (``design.md``, "Failures are swallowed").
    """
    try:
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=True)
        with transaction.atomic():
            RecentView.objects.update_or_create(
                user=user,
                content_type=content_type,
                object_id=obj.pk,
            )
            _prune(user)
    except Exception:
        logger.exception(
            "Failed to record recent view of %r for user %s", obj, getattr(user, "pk", user)
        )


def _prune(user: object) -> None:
    """Delete this user's ``RecentView`` rows past the newest ``RECENT_VIEW_LIMIT``."""
    stale_ids = list(
        RecentView.objects.filter(user=user)
        .order_by("-viewed_at")
        .values_list("pk", flat=True)[RECENT_VIEW_LIMIT:]
    )
    if stale_ids:
        RecentView.objects.filter(pk__in=stale_ids).delete()


def recent_for(user: object, limit: int = RECENT_LIMIT) -> list[object]:
    """The last ``limit`` objects ``user`` opened, newest first, filtered to what they can
    still see.

    Every referenced object is re-resolved through its own model's ``.visible_to(user)``: a row
    only records that the user *once* could see the object, and a stale row (object deleted, or
    access revoked) is skipped here and left in the table (``design.md``, "Security notes").
    Generic references are resolved with one ``visible_to`` query per content type.
    """
    rows = list(RecentView.objects.filter(user=user).order_by("-viewed_at"))
    if not rows:
        return []

    rows_by_ct: dict[int, list[RecentView]] = defaultdict(list)
    for row in rows:
        rows_by_ct[row.content_type_id].append(row)

    resolved: dict[tuple[int, int], object] = {}
    for content_type_id, ct_rows in rows_by_ct.items():
        model = ContentType.objects.get_for_id(content_type_id).model_class()
        manager = getattr(model, "objects", None) if model is not None else None
        if manager is None or not hasattr(manager, "visible_to"):
            continue
        object_ids = [row.object_id for row in ct_rows]
        for obj in manager.visible_to(user).filter(pk__in=object_ids):
            resolved[(content_type_id, obj.pk)] = obj

    visible: list[object] = []
    for row in rows:
        obj = resolved.get((row.content_type_id, row.object_id))
        if obj is None:
            continue
        visible.append(obj)
        if len(visible) >= limit:
            break
    return visible
