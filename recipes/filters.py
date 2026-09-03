"""``django-filter`` filter set for ``GET /api/recipes/`` (``Plan/05-Recipes/design.md``, "API").

Every filter here only ever *narrows* the queryset the view already scoped through
``OwnedViewSetMixin.get_queryset()`` → ``.visible_to(request.user)``, so none can surface a
recipe visibility excluded. ``mine`` / ``shared_with_me`` / ``public`` are not re-implemented
here — they come from ``core.filters.OwnedObjectFilterBackend``, which the mixin mounts
alongside ``DjangoFilterBackend``.

``min_rating`` and ``favorite`` read the **requester's** own ``RecipeStats`` rows, never the
owner's (design.md: "``min_rating`` / ``favorite`` must read the requester's ``RecipeStats``").
"""

from __future__ import annotations

import django_filters
from django.db.models import F, QuerySet

from recipes.models import Recipe, RecipeRole


class RecipeFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    #: Repeatable by slug — ``?tags=chicken&tags=beef`` (OR) — to line up with the UI's filter
    #: chips, matching ``catalog.filters.IngredientFilter``.
    tags = django_filters.CharFilter(method="filter_by_tag_slugs")
    role = django_filters.ChoiceFilter(choices=RecipeRole.choices)
    max_minutes = django_filters.NumberFilter(method="filter_max_minutes")
    min_rating = django_filters.NumberFilter(method="filter_min_rating")
    favorite = django_filters.BooleanFilter(method="filter_favorite")

    class Meta:
        model = Recipe
        fields = ["search", "tags", "role", "max_minutes", "min_rating", "favorite"]

    def filter_by_tag_slugs(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        slugs = [slug for slug in self.data.getlist(name) if slug]
        if not slugs:
            return queryset
        return queryset.filter(tags__slug__in=slugs).distinct()

    def filter_max_minutes(self, queryset: QuerySet, name: str, value: object) -> QuerySet:
        """Total hands-on-plus-cook time: ``prep_minutes + cook_minutes <= value``."""
        return queryset.annotate(_total_minutes=F("prep_minutes") + F("cook_minutes")).filter(
            _total_minutes__lte=value
        )

    def filter_min_rating(self, queryset: QuerySet, name: str, value: object) -> QuerySet:
        user = getattr(self.request, "user", None)
        return queryset.filter(stats__user=user, stats__rating__gte=value).distinct()

    def filter_favorite(self, queryset: QuerySet, name: str, value: bool) -> QuerySet:
        """``?favorite=true`` narrows to the requester's favourites. ``?favorite=false`` is
        treated as "no filter" rather than "recipes I actively un-favourited" — a recipe with no
        stats row is not a meaningful non-favourite.
        """
        if not value:
            return queryset
        user = getattr(self.request, "user", None)
        return queryset.filter(stats__user=user, stats__is_favorite=True).distinct()
