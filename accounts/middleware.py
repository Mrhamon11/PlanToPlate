"""Force a password change onto any authenticated user still on a temp password.

See ``Plan/01-Users-And-Auth/design.md`` ("The middleware") for the exemption list and the
API/HTML split this implements.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

HEALTHZ_PATH = "/healthz/"


def api_password_change_path() -> str:
    """The one ``/api/auth/`` path exempt from the forced-change block.

    Exact path, not an ``/api/auth/`` prefix — a prefix match would also exempt
    ``/api/auth/me/``. Reversed lazily (never at import time, since the URLconf may not be
    loaded yet) and shared with ``accounts.permissions.ForcePasswordChangeAPIPermission`` so
    the two exemptions cannot drift apart.
    """
    return reverse("accounts_api:password-change")


def api_logout_path() -> str:
    """``/api/auth/logout/`` — exempt for the same reason ``accounts:logout`` is: a user forced
    to change their password must still be able to leave.
    """
    return reverse("accounts_api:logout")


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
        # request.user is lazy — accessing it here (before the exemption check) is what runs
        # get_user()'s session-auth-hash comparison and flushes a stale session. Checking the
        # path first would skip that on an exempt path such as /healthz/.
        user = request.user
        if not user.is_authenticated or not user.must_change_password:
            return None
        if self._is_exempt(request.path):
            return None

        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "password_change_required"}, status=403)
        try:
            redirect_target = reverse("accounts:password_change")
        except NoReverseMatch:
            # Same fail-closed posture as _is_exempt() below: a URLconf that doesn't mount
            # accounts.urls (e.g. a test-only router) must deny rather than 500. There is no
            # HTML form to redirect to, so this denies the request outright instead of
            # crashing with an unhandled NoReverseMatch.
            return HttpResponseForbidden("password_change_required")
        return redirect(redirect_target)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        """Every exemption is reversed defensively (03.8a rework, non-blocking finding 4 —
        the same fail-open-under-a-partial-URLconf landmine NB4 already fixed one layer down in
        ``accounts.permissions.ForcePasswordChangeAPIPermission``): a URLconf that mounts
        ``accounts.urls`` but not ``accounts.api_urls`` (e.g. a test-only router) would
        otherwise turn a should-be-exempt request into an unhandled ``NoReverseMatch`` 500
        instead of the redirect/403 this middleware means to return. A name that fails to
        reverse is simply not added to the exempt set — it denies that specific path rather
        than crashing, which is the same "ambiguity resolves to less access, not more" rule
        every fail-closed check in this app follows.
        """
        exempt_paths = {HEALTHZ_PATH}
        for reverse_exempt_path in (
            lambda: reverse("accounts:password_change"),
            lambda: reverse("accounts:logout"),
            api_password_change_path,
            api_logout_path,
        ):
            try:
                exempt_paths.add(reverse_exempt_path())
            except NoReverseMatch:
                continue

        if path in exempt_paths:
            return True

        return path.startswith(settings.STATIC_URL) or path.startswith(settings.MEDIA_URL)
