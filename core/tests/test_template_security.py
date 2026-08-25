"""Template-layer security contracts — see Plan/02-UI-Shell/test-plan.md, "Security", and
design.md's "Security notes". Each test scans real template files rather than a hand-picked
sample, and each carries its own proof that the scan isn't vacuously passing.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

TEMPLATE_ROOT = Path(settings.BASE_DIR) / "templates"

# Deliberately empty. Any |safe or mark_safe usage must be added here explicitly, with a
# reviewed reason, before it can land — see test-plan.md, "Security" and design.md's
# "Django autoescaping stays on."
SAFE_FILTER_ALLOWLIST: frozenset[str] = frozenset()

SAFE_FILTER_RE = re.compile(r"\|\s*safe\b")
MARK_SAFE_RE = re.compile(r"\bmark_safe\b")
EXTERNAL_ASSET_RE = re.compile(r"""(?:src|href)=["\']https?://[^"\']+["\']""")
FORM_POST_RE = re.compile(r"""<form\b[^>]*\bmethod=["\']post["\']""", re.IGNORECASE)


def _all_templates() -> list[Path]:
    return list(TEMPLATE_ROOT.rglob("*.html"))


def test_no_unjustified_safe_filter():
    templates = _all_templates()
    assert templates, "no templates found under templates/ — the glob is broken"

    offenders = []
    for path in templates:
        relative_path = str(path.relative_to(TEMPLATE_ROOT))
        if relative_path in SAFE_FILTER_ALLOWLIST:
            continue
        content = path.read_text()
        if SAFE_FILTER_RE.search(content) or MARK_SAFE_RE.search(content):
            offenders.append(relative_path)

    assert offenders == [], f"unjustified |safe or mark_safe found in: {offenders}"


def test_no_unjustified_safe_filter_detector_actually_matches_a_real_usage():
    """The allowlist is empty right now, so the scan above passing could mean either "no
    template uses |safe" or "the regex is broken and never matches anything." This pins the
    regex against known-bad markup directly, independent of the current state of templates/.
    """
    assert SAFE_FILTER_RE.search("{{ note|safe }}")
    assert MARK_SAFE_RE.search("{{ mark_safe(value) }}")


def test_user_content_is_escaped(client, user_factory):
    user = user_factory(username="normal-user")
    # Bypasses the username validator on purpose — .save() doesn't run full_clean(). The
    # point is to prove template autoescaping holds regardless of whether this value could
    # organically reach the database, not to find a way past validation.
    user.username = "<script>alert(1)</script>"
    user.save(update_fields=["username"])
    client.force_login(user)

    response = client.get(reverse("core:home"))
    content = response.content.decode()

    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content


def test_no_external_resource_references():
    """No template references an off-host http(s):// asset — the app must load fully with no
    internet access (design.md, "Security notes").
    """
    templates = _all_templates()
    assert templates

    offenders = [
        (str(path.relative_to(TEMPLATE_ROOT)), match.group(0))
        for path in templates
        for match in EXTERNAL_ASSET_RE.finditer(path.read_text())
    ]

    assert offenders == [], f"off-host asset references found: {offenders}"


def test_no_external_resource_references_detector_catches_a_cdn_reference():
    """Pins the regex against a realistic CDN <script> tag so the passing scan above can't be
    explained by a detector that never matches anything.
    """
    offending_markup = '<script src="https://cdn.example.com/htmx.min.js"></script>'
    assert EXTERNAL_ASSET_RE.search(offending_markup)


def test_csrf_token_present_on_forms():
    templates = _all_templates()
    forms_found = 0
    offenders = []

    for path in templates:
        content = path.read_text()
        for match in FORM_POST_RE.finditer(content):
            forms_found += 1
            tail = content[match.end() :]
            close_index = tail.find("</form>")
            form_body = tail[: close_index if close_index != -1 else len(tail)]
            if "{% csrf_token %}" not in form_body:
                offenders.append(str(path.relative_to(TEMPLATE_ROOT)))

    assert forms_found > 0, 'no <form method="post"> found in any template — scan matched nothing'
    assert offenders == [], f"POST forms missing csrf_token: {offenders}"
