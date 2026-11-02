"""Rate limiting for plain Django views (10.5 — ``Plan/10-Security-And-Deployment/design.md``,
"Rate limiting").

DRF's ``throttle_classes``/``DEFAULT_THROTTLE_CLASSES`` only ever run for a DRF ``APIView`` —
the Django admin's custom user-management views/actions (``accounts/admin.py``) and the JSON
importer (``core/admin.py``) are plain function-based views with no such machinery. This mirrors
``accounts.throttling.check_login_throttle``'s shape (a function a view calls first, returning
an ``HttpResponse`` to short-circuit the request with, or ``None`` to let it proceed) and its
cache-based sliding-window algorithm, kept independent of DRF's throttle classes so it can be
called from a bare function with no ``view`` object to hand one.

Every caller here already requires an authenticated, staff session (the admin's own
``admin_view`` wrapper), so the identity a bucket is keyed on is the acting user's primary key,
never their IP — unlike the login throttle, there is no "which account is attacking which"
ambiguity once the caller must already be a real, logged-in staff member.
"""

from __future__ import annotations

import re
import time

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse

_RATE_PATTERN = re.compile(r"^(\d+)/(s|sec|second|m|min|minute|h|hour|d|day)$")

_PERIOD_SECONDS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
}

#: The same cache-key shape DRF's ``rest_framework.throttling.SimpleRateThrottle`` uses, so a
#: scope throttled from both a plain Django view (this module) and a DRF view
#: (``rest_framework.throttling.ScopedRateThrottle``) shares one real budget rather than each
#: side quietly keeping its own — the same "one shared bucket" property
#: ``accounts.throttling.LOGIN_THROTTLE_SCOPE`` already relies on across three endpoints.
_CACHE_KEY_FORMAT = "throttle_%(scope)s_%(ident)s"

#: One shared bucket per staff user across every custom account-management action
#: (``accounts.admin``'s create-user page, reset-password, grant/revoke-admin) — design.md,
#: "Rate limiting". Kept as one scope rather than one per action: the risk these guard against
#: (a compromised or malicious staff session hammering account-mutating endpoints) does not
#: care which specific action is being repeated.
ADMIN_ACTION_THROTTLE_SCOPE = "admin_action"
ADMIN_ACTION_THROTTLE_RATE = "30/min"

#: The bulk JSON importer (``core.admin.import_json_view``) — design.md, "Rate limiting". Its
#: own object-count/size/depth caps (``core/schemas.py``) bound any *one* request; this bounds
#: how often a staff session can fire the whole pipeline at all.
IMPORT_THROTTLE_SCOPE = "import"
IMPORT_THROTTLE_RATE = "5/hour"


def parse_rate(rate: str) -> tuple[int, int]:
    """``"30/min"`` -> ``(30, 60)``. Raises ``ValueError`` on anything else — a typo here is a
    silently-inert rate limit, not a 500 at request time.
    """
    match = _RATE_PATTERN.match(rate)
    if not match:
        raise ValueError(
            f"Invalid rate string {rate!r} — expected '<count>/<s|m|h|d|sec|min|hour|day>'."
        )
    count, period = match.groups()
    return int(count), _PERIOD_SECONDS[period]


def _cache_key(scope: str, ident: str) -> str:
    return _CACHE_KEY_FORMAT % {"scope": scope, "ident": ident}


def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


def check_rate_limit(
    request: HttpRequest, *, scope: str, rate: str, ident: str | None = None
) -> HttpResponse | None:
    """Returns a ``429`` ``JsonResponse`` (with ``Retry-After``) if the caller has exceeded
    ``rate`` for ``scope``; ``None`` if the request may proceed, having already recorded it.

    ``ident`` defaults to the authenticated requester's primary key, falling back to their IP
    only if somehow unauthenticated — every real caller (admin actions, the importer) is
    already behind ``admin_view``'s staff-session gate.
    """
    num_requests, duration = parse_rate(rate)
    if ident is None:
        user = getattr(request, "user", None)
        ident = str(user.pk) if getattr(user, "is_authenticated", False) else _client_ip(request)

    key = _cache_key(scope, ident)
    now = time.time()
    history = [timestamp for timestamp in cache.get(key, []) if timestamp > now - duration]

    if len(history) >= num_requests:
        oldest = min(history)
        retry_after = max(1, int(duration - (now - oldest)) + 1)
        response = JsonResponse(
            {"detail": f"Too many requests. Try again in {retry_after} seconds."},
            status=429,
        )
        response["Retry-After"] = str(retry_after)
        return response

    history.append(now)
    cache.set(key, history, duration)
    return None


__all__ = [
    "ADMIN_ACTION_THROTTLE_RATE",
    "ADMIN_ACTION_THROTTLE_SCOPE",
    "IMPORT_THROTTLE_RATE",
    "IMPORT_THROTTLE_SCOPE",
    "check_rate_limit",
    "parse_rate",
]
