"""Per-user dish stats, created lazily — the ``DishStats`` counterpart of
``recipes.services.stats`` (D3 / C4). Kept deliberately parallel: same function names, same
lazy-read / eager-write split, so the two never drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from meals.models import DishStats

if TYPE_CHECKING:
    from meals.models import Dish

_MIN_RATING = 1
_MAX_RATING = 5


def get_stats(user: object, dish: Dish) -> DishStats:
    """The user's stats for ``dish``: the persisted row if one exists, otherwise a fresh
    **unsaved** ``DishStats`` — reading stats never creates a row.
    """
    existing = DishStats.objects.filter(user=user, dish=dish).first()
    if existing is not None:
        return existing
    return DishStats(user=user, dish=dish)


@transaction.atomic
def mark_made(user: object, dish: Dish, *, when: object | None = None) -> DishStats:
    """Record that ``user`` cooked ``dish``: ``times_made`` += 1 and ``last_made_at`` stamped."""
    stats, _ = DishStats.objects.get_or_create(user=user, dish=dish)
    stats.times_made += 1
    stats.last_made_at = when or timezone.now()
    stats.save(update_fields=["times_made", "last_made_at"])
    return stats


@transaction.atomic
def set_rating(user: object, dish: Dish, rating: int | None) -> DishStats:
    """Set (or clear, with ``None``) the user's 1–5 rating for ``dish``."""
    if rating is not None and not (_MIN_RATING <= rating <= _MAX_RATING):
        raise ValidationError(
            f"Rating must be between {_MIN_RATING} and {_MAX_RATING}.",
            code="rating_out_of_range",
        )
    stats, _ = DishStats.objects.get_or_create(user=user, dish=dish)
    stats.rating = rating
    stats.save(update_fields=["rating"])
    return stats


@transaction.atomic
def toggle_favorite(user: object, dish: Dish) -> DishStats:
    """Flip the user's favourite flag for ``dish``."""
    stats, _ = DishStats.objects.get_or_create(user=user, dish=dish)
    stats.is_favorite = not stats.is_favorite
    stats.save(update_fields=["is_favorite"])
    return stats


@transaction.atomic
def set_favorite(user: object, dish: Dish, is_favorite: bool) -> DishStats:
    """Set the user's favourite flag for ``dish`` to a specific value — backs the idempotent
    ``PUT /api/dishes/<id>/stats/`` write.
    """
    stats, _ = DishStats.objects.get_or_create(user=user, dish=dish)
    stats.is_favorite = is_favorite
    stats.save(update_fields=["is_favorite"])
    return stats
