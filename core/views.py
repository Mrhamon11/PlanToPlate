"""Core views — the health check, and the post-login home/dashboard shell.

Business logic for this app (visibility querysets, sharing, copy services) lands in later
tasks; this file stays this small until then.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from core.mixins import HtmxTemplateMixin


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
    """The landing page after login — placeholder cards for the sections tasks 04-08 add.

    Doubles as 02.7's worked example of ``HtmxTemplateMixin``: the fragment template is the
    same partial the full page includes, so an HTMX refresh of this view and its initial load
    render identically from one piece of markup.
    """

    template_name = "core/home.html"
    partial_template_name = "core/_partials/_home_content.html"
    extra_context = {"nav_active": "home"}
