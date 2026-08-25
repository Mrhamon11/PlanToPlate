"""The HTMX contract every later screen depends on — see Plan/02-UI-Shell/test-plan.md,
"HTMX contract", and design.md's "Edge cases" for the redirect problem this middleware fixes.
"""

import pytest
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.clickjacking import XFrameOptionsMiddleware
from django.urls import reverse
from django.views.generic import TemplateView

from core.middleware import HtmxMiddleware
from core.mixins import HtmxTemplateMixin, MessageMixin

pytestmark = pytest.mark.django_db


def test_htmx_flag_set_from_header(rf):
    middleware = HtmxMiddleware(get_response=lambda request: HttpResponse())

    with_header = rf.get("/", HTTP_HX_REQUEST="true")
    middleware(with_header)
    assert with_header.htmx is True

    without_header = rf.get("/")
    middleware(without_header)
    assert without_header.htmx is False


def test_htmx_boosted_flag_set_from_header(rf):
    middleware = HtmxMiddleware(get_response=lambda request: HttpResponse())

    boosted = rf.get("/", HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true")
    middleware(boosted)
    assert boosted.htmx_boosted is True

    not_boosted = rf.get("/", HTTP_HX_REQUEST="true")
    middleware(not_boosted)
    assert not_boosted.htmx_boosted is False


def test_mixin_renders_fragment_for_htmx(client, user_factory):
    user = user_factory()
    client.force_login(user)

    full_page = client.get(reverse("core:home"))
    fragment = client.get(reverse("core:home"), HTTP_HX_REQUEST="true")

    assert full_page.status_code == fragment.status_code == 200
    assert b"Welcome back" in full_page.content
    assert b"Welcome back" in fragment.content
    assert b"<nav" in full_page.content
    assert b"<nav" not in fragment.content


def test_boosted_navigation_returns_full_document(client, user_factory):
    """C1 regression: hx-boost sends HX-Boosted alongside HX-Request, and htmx swaps a
    boosted response into document.body via innerHTML -- it wants the whole page, not the
    fragment HtmxTemplateMixin would otherwise serve for any HX-Request.
    """
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("core:home"), HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true")
    content = response.content.decode()

    assert response.status_code == 200
    assert "<nav" in content
    assert "</html>" in content


def test_fragment_response_has_no_html_tag(client, user_factory):
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("core:home"), HTTP_HX_REQUEST="true")
    content = response.content.decode()

    assert "<html" not in content
    assert "<body" not in content


def test_page_works_without_htmx(client, user_factory):
    """The full-page path is the real, no-JavaScript path — it must be complete, valid HTML
    on its own, with no HTMX request header involved.
    """
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("core:home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert content.strip().startswith("<!DOCTYPE html>")
    assert "<html" in content
    assert "</html>" in content
    assert "<body" in content
    assert "</body>" in content


def test_htmx_auth_failure_returns_hx_redirect(client):
    """An HTMX request to a login-required view must not 302 into a fragment swap — the
    browser would follow the redirect transparently and htmx would swap the login page's HTML
    into whatever element made the request (design.md, "Edge cases").
    """
    response = client.get(reverse("core:home"), HTTP_HX_REQUEST="true")

    assert response.status_code in (200, 204)
    assert response.status_code != 302
    assert "HX-Redirect" in response
    assert response["HX-Redirect"].startswith(reverse("accounts:login"))


def test_htmx_forced_password_change_redirect_also_uses_hx_redirect(client, user_factory):
    """The same fix must cover accounts.middleware.ForcePasswordChangeMiddleware's redirect,
    not just LoginRequiredMixin's — both are ordinary Django redirects by the time
    core.middleware.HtmxMiddleware sees them (see core/middleware.py's docstring).
    """
    user = user_factory(must_change_password=True)
    client.force_login(user)

    response = client.get(reverse("core:home"), HTTP_HX_REQUEST="true")

    assert response.status_code != 302
    assert response["HX-Redirect"] == reverse("accounts:password_change")


def test_htmx_redirect_preserves_messages_and_frame_options(rf, user_factory):
    """S1 regression: HtmxMiddleware must mutate the response it was handed rather than
    building a fresh HttpResponse(status=200), or every header/cookie written by middleware
    that sits inside it in MIDDLEWARE (MessageMiddleware, XFrameOptionsMiddleware) is silently
    dropped from the rewritten HX-Redirect response.

    Composes the same nesting the real MIDDLEWARE list uses -- HtmxMiddleware wraps
    MessageMiddleware, which wraps XFrameOptionsMiddleware -- so this exercises the real
    response-phase ordering, not a hand-built response.
    """

    def inner_view(request):
        messages.success(request, "Saved.")
        return HttpResponseRedirect("/landing/")

    with_frame_options = XFrameOptionsMiddleware(inner_view)
    with_messages = MessageMiddleware(with_frame_options)
    middleware = HtmxMiddleware(with_messages)

    request = rf.get("/", HTTP_HX_REQUEST="true")
    request.user = user_factory()
    # FallbackStorage needs request.session to exist -- normally SessionMiddleware's job,
    # which this hand-composed chain bypasses entirely.
    request.session = SessionStore()

    response = middleware(request)

    assert response.status_code == 200
    assert response["HX-Redirect"] == "/landing/"
    assert "Location" not in response
    assert "messages" in response.cookies, (
        "the flash-message cookie MessageMiddleware wrote must survive the HX-Redirect rewrite"
    )
    assert response["X-Frame-Options"] == "DENY"


class _DemoMessageView(MessageMixin, HtmxTemplateMixin, LoginRequiredMixin, TemplateView):
    """A minimal HtmxTemplateMixin + MessageMixin view, used only by
    test_messages_included_as_oob_on_htmx below — no domain view exists yet that raises a
    message from a fragment response.
    """

    template_name = "core/home.html"
    partial_template_name = "core/_partials/_home_content.html"

    def get(self, request, *args, **kwargs):
        self.add_message(messages.SUCCESS, "Saved.")
        return super().get(request, *args, **kwargs)


def test_messages_included_as_oob_on_htmx(rf, user_factory):
    request = rf.get("/", HTTP_HX_REQUEST="true")
    request.htmx = True
    request.user = user_factory()
    # FallbackStorage falls back to session storage, which needs request.session to exist —
    # normally SessionMiddleware's job, which RequestFactory bypasses entirely.
    request.session = SessionStore()
    request._messages = FallbackStorage(request)

    response = _DemoMessageView.as_view()(request)
    response.render()

    assert response.status_code == 200
    assert b"hx-swap-oob" in response.content
    assert b"Saved." in response.content
