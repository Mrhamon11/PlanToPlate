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

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from rest_framework.throttling import ScopedRateThrottle

LOGIN_THROTTLE_SCOPE = "login"

#: Shared by ``accounts.views.ForcedAwarePasswordChangeView`` *and*
#: ``accounts.api.PasswordChangeAPIView`` — both call
#: ``core.services.ratelimit.check_rate_limit`` directly against this scope/rate, the same one
#: real bucket per user across both surfaces, the same "one shared budget across every endpoint
#: doing the same thing" shape as the login throttle above. ``PasswordChangeAPIView`` used to run
#: DRF's own ``ScopedRateThrottle`` against the same cache key instead — an incompatible list
#: algorithm sharing one key with ``check_rate_limit``, which corrupted the bucket and produced
#: false 429s (task 10 review, blocking finding). Routing both surfaces through the same function
#: fixed that and, as a side effect, makes this the only literal for the rate — there is no
#: second copy in ``config.settings.base``'s ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` to keep
#: in sync with it any more.
PASSWORD_CHANGE_THROTTLE_SCOPE = "password_change"  # noqa: S105 - a throttle scope, not a secret
PASSWORD_CHANGE_THROTTLE_RATE = "5/min"  # noqa: S105 - a throttle rate, not a secret


class _LoginThrottleTarget:
    """Stands in for the ``view`` argument ``ScopedRateThrottle.allow_request`` reads
    ``throttle_scope`` off of. Neither the HTML login view nor ``/admin/login/`` is a DRF
    view, so there is no real one to pass — this is the only attribute the throttle ever
    reads from it.
    """

    throttle_scope = LOGIN_THROTTLE_SCOPE


class LoginRateThrottle(ScopedRateThrottle):
    """Keys the login bucket on the requester's IP unconditionally — never on
    ``request.user.pk`` (10.5 carried finding from 01.8).

    ``ScopedRateThrottle.get_cache_key`` keys on ``request.user.pk`` whenever the request is
    *authenticated*, falling back to IP only when it is not. For every other scope that is the
    right call (rate-limit a signed-in user's own actions by their own identity). For a login
    endpoint specifically it is backwards: a login POST's whole purpose is to attack an
    identity the requester does not yet hold, so keying on "whoever the requester currently is"
    lets an attacker holding (or freely creating) one valid account draw a fresh 5/min budget
    per account it controls, all against the very same target, from the very same address
    (ARCHITECTURE.md D25). A login attempt's identity is the network address making it, full
    stop — never the session, if any, that happens to already be live on it.
    """

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _reset_key_for(request: HttpRequest) -> str:
    throttle = LoginRateThrottle()
    ident = throttle.get_ident(request)
    return throttle.cache_format % {"scope": LOGIN_THROTTLE_SCOPE, "ident": ident}


def reset_login_throttle(request: HttpRequest) -> None:
    """Clears the login throttle bucket for ``request``'s IP.

    Called after every *successful* login (all three endpoints) — 10.5 carried finding: without
    this, a real login still spends one slot from the shared 5/min budget, so a household behind
    one NAT address (several people, or one person's own earlier typo) can throttle a
    subsequent legitimate login purely on volume, with no wrong password anywhere in the mix.
    A successful login is proof the address is not currently mid-attack; there is nothing left
    to protect by keeping its count.
    """
    cache.delete(_reset_key_for(request))


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
    throttle = LoginRateThrottle()
    if throttle.allow_request(request, _LoginThrottleTarget()):
        return None

    wait = throttle.wait()
    wait_seconds = int(wait) + 1 if wait is not None else None
    body = render_to_string("429.html", {"wait_seconds": wait_seconds}, request=request)
    response = HttpResponse(body, status=429)
    if wait_seconds is not None:
        response["Retry-After"] = str(wait_seconds)
    return response
