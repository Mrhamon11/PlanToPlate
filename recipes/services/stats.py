"""Per-user recipe stats, created lazily (design.md, "Per-user stats"; D3 / C4).

Most users never rate most recipes, so a ``RecipeStats`` row per user per recipe up front is
waste. ``get_stats`` returns an *unsaved* instance when no row exists; only the three mutators
(``mark_made``, ``set_rating``, ``toggle_favorite``) call ``get_or_create`` and persist. Every
caller goes through here so the laziness is not their problem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from recipes.models import RecipeStats

if TYPE_CHECKING:
    from recipes.models import Recipe

_MIN_RATING = 1
_MAX_RATING = 5


def get_stats(user: object, recipe: Recipe) -> RecipeStats:
    """The user's stats for ``recipe``. Returns the persisted row if one exists, otherwise a
    fresh **unsaved** ``RecipeStats`` with default values — reading stats never creates a row.
    """
    existing = RecipeStats.objects.filter(user=user, recipe=recipe).first()
    if existing is not None:
        return existing
    return RecipeStats(user=user, recipe=recipe)


@transaction.atomic
def mark_made(user: object, recipe: Recipe, *, when: object | None = None) -> RecipeStats:
    """Record that ``user`` cooked ``recipe``: ``times_made`` += 1 and ``last_made_at`` stamped
    (this is the field the planner's ``no_repeat_days`` gear reads).
    """
    stats, _ = RecipeStats.objects.get_or_create(user=user, recipe=recipe)
    stats.times_made += 1
    stats.last_made_at = when or timezone.now()
    stats.save(update_fields=["times_made", "last_made_at"])
    return stats


@transaction.atomic
def set_rating(user: object, recipe: Recipe, rating: int | None) -> RecipeStats:
    """Set (or clear, with ``None``) the user's 1–5 rating for ``recipe``.

    Raises ``ValidationError`` for anything outside 1–5 — the same bound the model validator and
    the database ``CheckConstraint`` enforce, surfaced here as a clean error at the boundary.
    """
    if rating is not None and not (_MIN_RATING <= rating <= _MAX_RATING):
        raise ValidationError(
            f"Rating must be between {_MIN_RATING} and {_MAX_RATING}.",
            code="rating_out_of_range",
        )
    stats, _ = RecipeStats.objects.get_or_create(user=user, recipe=recipe)
    stats.rating = rating
    stats.save(update_fields=["rating"])
    return stats


@transaction.atomic
def toggle_favorite(user: object, recipe: Recipe) -> RecipeStats:
    """Flip the user's favourite flag for ``recipe`` and return the row."""
    stats, _ = RecipeStats.objects.get_or_create(user=user, recipe=recipe)
    stats.is_favorite = not stats.is_favorite
    stats.save(update_fields=["is_favorite"])
    return stats
