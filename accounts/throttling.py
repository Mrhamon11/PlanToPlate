"""The one login-attempt throttle scope, shared by all three credential-accepting endpoints.

See ``Plan/01-Users-And-Auth/design.md``, "Login throttling" — the HTML login view
(``accounts.views.ThrottledLoginMixin``), the API login (``accounts.api.LoginAPIView``, via
DRF's own ``throttle_classes``), and ``/admin/login/`` (``accounts.views.throttled_admin_login``)
all share one ``ScopedRateThrottle`` scope/bucket, so an attacker cannot dodge the 5/min budget
by switching endpoints. What they share is ``LOGIN_THROTTLE_SCOPE`` — the API login goes through
DRF's own ``throttle_classes``/``throttle_scope`` machinery, and only the two Django-side paths
call ``check_login_throttle`` below. Extracted here rather than duplicated, after iteration 1's
security review found ``/admin/login/`` was throttled by none of them.
"""

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from rest_framework.throttling import ScopedRateThrottle

LOGIN_THROTTLE_SCOPE = "login"


class _LoginThrottleTarget:
    """Stands in for the ``view`` argument ``ScopedRateThrottle.allow_request`` reads
    ``throttle_scope`` off of. Neither the HTML login view nor ``/admin/login/`` is a DRF
    view, so there is no real one to pass — this is the only attribute the throttle ever
    reads from it.
    """

    throttle_scope = LOGIN_THROTTLE_SCOPE


def check_login_throttle(request: HttpRequest) -> HttpResponse | None:
    """Returns a 429 ``HttpResponse`` if ``request`` should be throttled, else ``None``.

    Works against a plain Django ``HttpRequest``, not just a DRF ``Request`` —
    ``ScopedRateThrottle`` only reads ``request.META``/``request.headers``/``request.user``,
    all of which a plain request already provides, so no wrapping is needed to reuse it outside
    a DRF view.

    Renders ``429.html`` (task 02.11 — deferred from 01.8/D25) rather than the bare
    ``text/plain`` body this returned originally: a styled page that states the wait and says
    outright that no account has been locked, since D25's whole design is that this throttle
    never locks one. ``Retry-After`` is still set to the same integer the template renders
    into its body, so an HTTP-aware client and a human reading the page agree on the wait.
    """
    throttle = ScopedRateThrottle()
    if throttle.allow_request(request, _LoginThrottleTarget()):
        return None

    wait = throttle.wait()
    wait_seconds = int(wait) + 1 if wait is not None else None
    body = render_to_string("429.html", {"wait_seconds": wait_seconds}, request=request)
    response = HttpResponse(body, status=429)
    if wait_seconds is not None:
        response["Retry-After"] = str(wait_seconds)
    return response
