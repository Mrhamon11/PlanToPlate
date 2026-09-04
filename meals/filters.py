"""``django-filter`` filter sets for the meals list endpoints
(``Plan/06-Dishes-And-RecipeBooks/design.md``, "API").

Every filter here only ever *narrows* the queryset the view already scoped through
``OwnedViewSetMixin.get_queryset()`` → ``.visible_to(request.user)``, so none can surface a
row it excluded. ``mine`` / ``shared_with_me`` / ``public`` come from
``core.filters.OwnedObjectFilterBackend``, not re-implemented here.
"""

from __future__ import annotations

import django_filters
from django.db.models import QuerySet

from meals.models import Dish, RecipeBook
from recipes.models import RecipeRole


class DishFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    tags = django_filters.CharFilter(method="filter_by_tag_slugs")
    role = django_filters.ChoiceFilter(choices=RecipeRole.choices, method="filter_role")
    favorite = django_filters.BooleanFilter(method="filter_favorite")

    class Meta:
        model = Dish
        fields = ["search", "tags", "role", "favorite"]

    def filter_by_tag_slugs(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        slugs = [slug for slug in self.data.getlist(name) if slug]
        if not slugs:
            return queryset
        return queryset.filter(tags__slug__in=slugs).distinct()

    def filter_role(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """A dish matches a role if any of its component recipes has it — used by the planner
        to pick a dish for a ``BALANCED`` slot.
        """
        return queryset.filter(components__recipe__role=value).distinct()

    def filter_favorite(self, queryset: QuerySet, name: str, value: bool) -> QuerySet:
        if not value:
            return queryset
        user = getattr(self.request, "user", None)
        return queryset.filter(stats__user=user, stats__is_favorite=True).distinct()


class RecipeBookFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = RecipeBook
        fields = ["search"]
