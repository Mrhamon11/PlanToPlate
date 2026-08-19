"""Core views — currently just the health check.

Business logic for this app (visibility querysets, sharing, copy services) lands in later
tasks; this file stays this small until then.
"""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe


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
