"""Core views — the health check, the post-login home dashboard, and the per-panel fragment
endpoints (``Plan/12-Home-Dashboard/design.md``).

The dashboard's panel logic lives entirely in ``core.services.dashboard``; these views only
hand the assembled ``DashboardContext`` to a template.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from core.mixins import HtmxTemplateMixin
from core.services.dashboard import build_dashboard


@require_safe
def healthz(request):
    """Report whether the app and its database are reachable.

    Backed by a real ``SELECT 1`` round trip rather than just returning a static 200 — a
    health check that cannot detect an unhealthy database is decoration, not monitoring.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # any DB failure means "unhealthy", not just specific driver errors
        return JsonResponse({"status": "error", "database": "error"}, status=503)

    return JsonResponse({"status": "ok", "database": "ok"})


class HomeView(LoginRequiredMixin, HtmxTemplateMixin, TemplateView):
    """The landing page after login — the home dashboard (task 12).

    Every panel is rendered server-side on this first request (``design.md``, "Rendering, and
    the no-JS rule"): there is no ``hx-trigger="load"`` anywhere, so the page is complete with
    JavaScript disabled. An HTMX refresh of this same view re-renders
    ``_partials/_home_content.html`` from the same ``DashboardContext``.
    """

    template_name = "core/home.html"
    partial_template_name = "core/_partials/_home_content.html"
    extra_context = {"nav_active": "home"}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["dashboard"] = build_dashboard(self.request.user)
        return context


#: URL segment -> (partial template, ``DashboardContext`` attribute the panel needs).
_DASHBOARD_PANELS = {
    "this-week": "core/_partials/_panel_this_week.html",
    "shopping": "core/_partials/_panel_shopping.html",
    "recent": "core/_partials/_panel_recent.html",
    "favourites": "core/_partials/_panel_favourites.html",
    "shared": "core/_partials/_panel_shared.html",
    "public": "core/_partials/_panel_public.html",
    "suggestion": "core/_partials/_panel_suggestion.html",
    "sections": "core/_partials/_panel_sections.html",
}


class DashboardPanelView(LoginRequiredMixin, View):
    """``/dashboard/panel/<name>/`` — re-render one dashboard panel on its own.

    **An enhancement, never the delivery mechanism** (``design.md``, "Rendering, and the no-JS
    rule"): every panel is already in the first full-page response, so nothing here uses
    ``hx-trigger="load"``. The panels that re-roll or tick in place (``suggestion``, a future
    ``shopping``) point an ``hx-get`` here with an explicit ``hx-target`` on their panel
    element (D39), and fall back to a full-page GET of ``core:home`` without JavaScript.
    """

    def get(self, request: HttpRequest, name: str) -> HttpResponse:
        try:
            template = _DASHBOARD_PANELS[name]
        except KeyError as exc:
            raise Http404(f"Unknown dashboard panel {name!r}") from exc
        return render(request, template, {"dashboard": build_dashboard(request.user)})
