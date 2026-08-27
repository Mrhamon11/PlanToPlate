"""``django-filter`` filter sets for the catalog list endpoints
(``Plan/04-Units-And-Ingredients/design.md``, "API").

Every filter here only ever *narrows* the queryset the view already handed it. For
``IngredientViewSet`` that queryset has already been through
``OwnedViewSetMixin.get_queryset()`` → ``.visible_to(request.user)``, so ``search``/``tags``/
``is_staple`` compose with the visibility keystone and cannot surface a row it excluded
(test-plan "Security": ``test_search_does_not_leak_invisible_rows``). ``?mine=`` is not
re-implemented here — it is already provided by ``core.filters.OwnedObjectFilterBackend``,
which ``OwnedViewSetMixin`` mounts alongside ``DjangoFilterBackend``.
"""

from __future__ import annotations

import django_filters

from catalog.models import Ingredient, Tag, Unit


class UnitFilter(django_filters.FilterSet):
    class Meta:
        model = Unit
        fields = ["dimension", "count_family"]


class TagFilter(django_filters.FilterSet):
    class Meta:
        model = Tag
        fields = ["kind"]


class IngredientFilter(django_filters.FilterSet):
    #: ``icontains`` goes through the ORM as a bound parameter and Django escapes LIKE
    #: wildcards in it, so a literal ``%`` or ``_`` in the term matches itself
    #: (test-plan "Security": ``test_sql_wildcards_in_search_are_literal``).
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    #: Repeatable by slug — ``?tags=chicken&tags=beef`` (OR) — to line up with the UI's filter
    #: chips. A method filter rather than ``ModelMultipleChoiceFilter`` so a single ``CharField``
    #: reads every repeat of the param off the raw QueryDict.
    tags = django_filters.CharFilter(method="filter_by_tag_slugs")
    is_staple = django_filters.BooleanFilter()

    class Meta:
        model = Ingredient
        fields = ["search", "tags", "is_staple"]

    def filter_by_tag_slugs(self, queryset, name, value):
        slugs = [slug for slug in self.data.getlist(name) if slug]
        if not slugs:
            return queryset
        return queryset.filter(tags__slug__in=slugs).distinct()
