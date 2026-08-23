"""Views for authentication and the temp-password flow.

Only a placeholder exists here for subtasks 01.1-01.5. The real login, logout,
password-change and profile views land in subtask 01.6 (see
Plan/01-Users-And-Auth/tasks.md); this file is a forward reference kept deliberately
minimal, not an implementation of that subtask.
"""

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "POST"])
def password_change_placeholder(request: HttpRequest) -> HttpResponse:
    """Stand in for the real ``PasswordChangeView`` that subtask 01.6 adds at this URL.

    Its only job right now is to give ``ForcePasswordChangeMiddleware`` a real, resolvable
    redirect target and to let the middleware's own exemption logic be tested — a request to
    this URL must never itself be redirected. It performs no password change.
    """
    return HttpResponse(status=204)
