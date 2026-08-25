"""HTMX request detection and the HTMX-aware redirect fix.

See ``Plan/02-UI-Shell/design.md``, "HTMX conventions" and "Edge cases", for why both halves
live in one middleware.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

#: Status codes Django's own redirect helpers (HttpResponseRedirect and friends) use. A plain
#: HttpResponse with a hand-set Location header and one of these codes is treated the same way.
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class HtmxMiddleware:
    """Sets ``request.htmx`` from the ``HX-Request`` header, and rewrites any redirect response
    to an HTMX request into a 200 carrying an ``HX-Redirect`` header instead.

    **Why the rewrite is needed at all:** a browser's XHR/fetch implementation follows a 3xx
    response automatically, inside the network stack, before any JavaScript — including
    htmx's own — ever sees it. By the time htmx inspects the response, the redirect has
    already happened silently and the *target* page's HTML (e.g. the login form) comes back
    dressed as an ordinary 200. htmx then swaps that into whatever element made the request,
    because nothing distinguishes it from a normal fragment — the classic "login form appears
    inside a card" bug. Returning ``HX-Redirect`` on a non-3xx response sidesteps this
    entirely: since the status is not a redirect, the browser never auto-follows it, and
    htmx's own response handler reads the header and navigates the whole page itself
    (``window.location = ...``).

    **Why this covers both failure modes design.md names, not just one:** any view (or
    middleware) that redirects during an HTMX request has the same problem, regardless of
    *why* it redirected — a plain ``LoginRequiredMixin`` 302 on session expiry, and
    ``accounts.middleware.ForcePasswordChangeMiddleware``'s ``redirect(...)`` to the forced
    change form, are both ordinary Django redirects by the time they reach here. Rewriting
    generically at the response-header level, rather than special-casing either call site,
    means neither of those places needs to know or care whether the request was HTMX.

    **Placement matters.** This must sit *before* ``ForcePasswordChangeMiddleware`` in
    ``MIDDLEWARE`` (earlier in the list = wraps it from the outside), so that middleware's
    redirect response passes back up through this one's response-phase code on its way out.
    It does not need to sit after ``AuthenticationMiddleware`` — request-flag detection only
    reads a header — but MIDDLEWARE keeps it there anyway, immediately before
    ``ForcePasswordChangeMiddleware``, so the ordering constraint that actually matters (must
    wrap it) is visually obvious from the list rather than incidental.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.htmx = request.headers.get("HX-Request") == "true"
        # htmx sets this alongside HX-Request for an hx-boost navigation, whose swap target is
        # document.body via innerHTML -- it wants the whole page, not a fragment. See
        # core.mixins.HtmxTemplateMixin, which is the thing that reads this flag.
        request.htmx_boosted = request.headers.get("HX-Boosted") == "true"
        response = self.get_response(request)

        if request.htmx and response.status_code in REDIRECT_STATUS_CODES:
            location = response.get("Location")
            if location:
                # Mutate the response we were handed rather than building a new one, so
                # response.cookies and every header inner middleware already set (e.g.
                # MessageMiddleware's flash-message cookie, XFrameOptionsMiddleware's
                # X-Frame-Options) survive the rewrite instead of being discarded.
                response.status_code = 200
                response["HX-Redirect"] = location
                del response["Location"]
                response.content = b""

        return response
