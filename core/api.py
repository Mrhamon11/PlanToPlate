"""Read-only home-dashboard API (``Plan/12-Home-Dashboard/design.md``, "Reading the
dashboard").

``GET /api/dashboard/`` serialises the same ``core.services.dashboard.DashboardContext`` the
HTMX home page renders — a future native client's home screen is the same query, and building
the panel logic twice is exactly what ``ARCHITECTURE.md`` section 6 forbids. There is no
write verb: a dashboard is a view of other resources, each of which has its own endpoint.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.serializers import DashboardSerializer
from core.services.dashboard import build_dashboard


class DashboardAPIView(APIView):
    """The current user's assembled dashboard. Authentication is the project default
    (``IsAuthenticated`` + ``ForcePasswordChangeAPIPermission``); every panel is already
    scoped to ``request.user`` inside ``build_dashboard`` — a ``RecentView`` row, a favourite,
    a shared object are all filtered by the requester, never by object ownership alone.
    """

    @extend_schema(responses=DashboardSerializer)
    def get(self, request: Request) -> Response:
        context = build_dashboard(request.user)
        return Response(DashboardSerializer(context).data)
