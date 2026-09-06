"""``django-filter`` filter set for ``GET /api/lists/`` (``Plan/07-Lists-And-Shopping/
design.md``, "API": "Filter by ``kind``, plus the standard owned filters").

Both filters here only ever *narrow* the queryset ``OwnedViewSetMixin.get_queryset()`` already
scoped through ``.visible_to(request.user)``. ``mine`` / ``shared_with_me`` / ``public`` come
from ``core.filters.OwnedObjectFilterBackend``, not re-implemented here.
"""

from __future__ import annotations

import django_filters

from lists.models import List, ListKind


class ListFilter(django_filters.FilterSet):
    kind = django_filters.ChoiceFilter(choices=ListKind.choices)
    search = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = List
        fields = ["kind", "search"]
