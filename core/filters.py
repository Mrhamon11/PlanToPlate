"""Query filters for owned-resource list endpoints (design.md, "API surface": ``?mine=true``,
``?shared_with_me=true``, ``?public=true``).

``OwnedObjectFilterBackend`` runs strictly *after* ``OwnedViewSetMixin.get_queryset()`` has
already scoped the queryset through ``.visible_to(request.user)`` — every branch below only
narrows further with another ``.filter()``, so none of them can ever surface a row
``visible_to()`` excluded (MILESTONES.md section 6: "never hand-roll an ownership filter"; the
IDOR matrix's ``test_filters_cannot_bypass_visibility``).
"""

from __future__ import annotations

from typing import Any

from rest_framework.filters import BaseFilterBackend
from rest_framework.request import Request
from rest_framework.viewsets import ViewSetMixin


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class OwnedObjectFilterBackend(BaseFilterBackend):
    def filter_queryset(self, request: Request, queryset: Any, view: ViewSetMixin) -> Any:
        from core.models import Visibility

        params = request.query_params

        if _is_true(params.get("mine")):
            queryset = queryset.filter(owner=request.user)
        if _is_true(params.get("shared_with_me")):
            queryset = queryset.filter(shared_with=request.user)
        if _is_true(params.get("public")):
            queryset = queryset.filter(visibility=Visibility.PUBLIC)

        return queryset.distinct()
