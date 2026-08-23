"""Force a password change onto any authenticated user still on a temp password.

See ``Plan/01-Users-And-Auth/design.md`` ("The middleware") for the exemption list and the
API/HTML split this implements.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

# Fallback only. The logout view does not exist until subtask 01.6, so ``reverse()`` cannot
# resolve ``accounts:logout`` yet — ``_is_exempt`` tries the real name first and falls back to
# this hardcoded string on ``NoReverseMatch``. Once 01.6 mounts logout, the real name wins and
# this constant stops being read for anything but the self-check in
# ``test_forced_password_change.py`` that keeps the two from silently drifting apart.
LOGOUT_PATH = "/accounts/logout/"
HEALTHZ_PATH = "/healthz/"


class ForcePasswordChangeMiddleware:
    """Redirect any authenticated user with ``must_change_password=True`` to the change form.

    Enforced once, centrally, for every request — a per-view check is a per-view chance to
    forget it. API requests (``/api/...``) get a 403 with a machine-readable JSON body instead
    of a redirect, since a REST client cannot follow a redirect to an HTML form.

    Must sit after ``AuthenticationMiddleware`` in ``MIDDLEWARE`` — it reads ``request.user``
    and raises ``ImproperlyConfigured`` (mirroring ``AuthenticationMiddleware``'s own check for
    a missing ``SessionMiddleware``) rather than silently skipping enforcement if that ordering
    is ever broken.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        blocked = self._blocked_response(request)
        if blocked is not None:
            return blocked
        return self.get_response(request)

    def _blocked_response(self, request: HttpRequest) -> HttpResponse | None:
        if not hasattr(request, "user"):
            raise ImproperlyConfigured(
                "ForcePasswordChangeMiddleware requires authentication middleware to be "
                "installed. Edit your MIDDLEWARE setting to insert "
                "'django.contrib.auth.middleware.AuthenticationMiddleware' before "
                "'accounts.middleware.ForcePasswordChangeMiddleware'."
            )
        # Reading request.user before the exemption check is load-bearing, not incidental
        # ordering. request.user is lazy, and it is that access which runs django.contrib.auth
        # .get_user() — the session-auth-hash comparison that flushes a session whose password
        # has since changed. A view that never touches request.user (core.views.healthz, say)
        # would otherwise leave a stale session row alive on an exempt path. Checking the path
        # first would look like a harmless optimisation and would silently break that.
        user = request.user
        if not user.is_authenticated or not user.must_change_password:
            return None
        if self._is_exempt(request.path):
            return None

        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "password_change_required"}, status=403)
        return redirect(reverse("accounts:password_change"))

    @staticmethod
    def _is_exempt(path: str) -> bool:
        try:
            logout_path = reverse("accounts:logout")
        except NoReverseMatch:
            logout_path = LOGOUT_PATH

        exempt_paths = {
            reverse("accounts:password_change"),
            logout_path,
            HEALTHZ_PATH,
        }
        if path in exempt_paths:
            return True

        return path.startswith(settings.STATIC_URL) or path.startswith(settings.MEDIA_URL)
