"""Content Security Policy (10.4 — ``Plan/10-Security-And-Deployment/test-plan.md``).

Achievable this strictly — no ``'unsafe-inline'`` anywhere — because task 02 vendored every
asset into ``static/`` and banned CDNs outright. See ``config/settings/base.py``'s
``CONTENT_SECURITY_POLICY`` for the policy itself and the one deliberate exception
(``templates/500.html``'s inline ``<style>``, allowed by exact content hash).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse

BASE_DIR = Path(settings.BASE_DIR)

#: Every attribute name that fires inline JavaScript — the full set of "on*" event-handler
#: attributes this project could plausibly use, not just the ones already found and fixed.
_INLINE_EVENT_ATTRS = (
    "onclick",
    "onchange",
    "onsubmit",
    "onload",
    "onerror",
    "oninput",
    "onkeyup",
    "onkeydown",
    "onkeypress",
    "onfocus",
    "onblur",
    "onmouseover",
    "onmouseout",
    "ondblclick",
)
_INLINE_EVENT_PATTERN = re.compile(r"\s(" + "|".join(_INLINE_EVENT_ATTRS) + r")\s*=", re.IGNORECASE)


def test_csp_header_present(client):
    response = client.get(reverse("accounts:login"))

    assert "Content-Security-Policy" in response


def test_csp_has_no_unsafe_inline_script(client):
    response = client.get(reverse("accounts:login"))

    policy = response["Content-Security-Policy"]
    script_src = [part for part in policy.split(";") if part.strip().startswith("script-src")]
    assert script_src, f"no script-src directive in policy: {policy}"
    assert "'unsafe-inline'" not in script_src[0]


def test_csp_style_src_has_no_unsafe_inline():
    """No blanket escape hatch either — the one legitimate inline style (500.html) is allowed
    by its exact content hash, asserted separately below, not by loosening this directive.
    """
    directives = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]

    assert "'unsafe-inline'" not in directives["style-src"]


def test_csp_frame_ancestors_none(client):
    response = client.get(reverse("accounts:login"))

    policy = response["Content-Security-Policy"]
    frame_ancestors = [
        part for part in policy.split(";") if part.strip().startswith("frame-ancestors")
    ]
    assert frame_ancestors, f"no frame-ancestors directive in policy: {policy}"
    assert "'none'" in frame_ancestors[0]


def test_no_inline_event_handlers_in_templates():
    """Greps every template for ``onclick=`` and friends (test-plan.md). The three inline
    handlers task 10 found (``recipe_print.html``, two admin temp-password "Copy" buttons, and
    two HTMX auto-submit ``onchange=`` attributes) were refactored into
    ``static/js/print-trigger.js`` / ``static/js/admin-copy.js`` / ``static/js/auto-submit.js``
    rather than excused — this proves none come back.
    """
    templates_dir = BASE_DIR / "templates"
    offenders = []
    for path in templates_dir.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if _INLINE_EVENT_PATTERN.search(text):
            offenders.append(str(path.relative_to(BASE_DIR)))

    assert offenders == [], f"inline event handler attribute(s) found in: {offenders}"


def test_no_inline_event_handler_check_is_actually_detected(tmp_path):
    """Proves the grep above is not vacuous: a template with a real inline handler must match
    the same pattern the real check uses.
    """
    sample = tmp_path / "sample.html"
    sample.write_text('<button onclick="doThing()">Go</button>', encoding="utf-8")

    assert _INLINE_EVENT_PATTERN.search(sample.read_text(encoding="utf-8"))


def test_htmx_does_not_inject_inline_indicator_styles():
    """htmx writes an inline ``<style>`` into ``<head>`` on load unless told not to, and the
    strict ``style-src`` blocks it (a console violation on every page in a real browser).
    ``components.css`` already carries the ``.htmx-indicator`` rules, so the injection is
    switched off in ``base.html``.
    """
    html = render_to_string("base.html")

    match = re.search(r'<meta name="htmx-config" content=\'([^\']*)\'', html)
    assert match, "base.html must carry an htmx-config meta tag"
    assert json.loads(match.group(1))["includeIndicatorStyles"] is False


def test_htmx_indicator_rules_live_in_our_own_stylesheet():
    css = (BASE_DIR / "static" / "css" / "components.css").read_text(encoding="utf-8")

    assert ".htmx-indicator" in css
    assert ".htmx-request" in css


def test_500_page_style_hash_matches_template():
    """``templates/500.html``'s one inline ``<style>`` block is allowed into ``style-src`` by
    exact SHA-256 content hash (``config/settings/base.py``) rather than by loosening the
    directive to ``'unsafe-inline'``. If that template's CSS is ever edited without
    regenerating the hash, the browser silently drops the styling and logs a CSP violation on
    every 500 error — this catches the drift here instead.
    """
    html = render_to_string("500.html")
    start = html.index("<style>") + len("<style>")
    end = html.index("</style>")
    style_body = html[start:end]
    digest = hashlib.sha256(style_body.encode("utf-8")).digest()
    computed_hash = "sha256-" + base64.b64encode(digest).decode()

    assert computed_hash in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]["style-src"]
