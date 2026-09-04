"""Template-layer contract tests (design.md, "Template architecture") — see
Plan/02-UI-Shell/test-plan.md, "Rendering".
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.views import TempPasswordAwarePasswordChangeForm
from conftest import DEFAULT_TEST_PASSWORD

pytestmark = pytest.mark.django_db

TEMPLATE_ROOT = Path(settings.BASE_DIR) / "templates"
EXTENDS_BASE_RE = re.compile(r"""{%\s*extends\s+["']base\.html["']\s*%}""")


def test_base_template_renders(client, user_factory):
    """core.views.HomeView extends base.html — its full-page response must carry the nav
    landmark and the messages container base.html always includes.
    """
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("core:home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert '<nav class="nav-top"' in content
    assert 'id="messages"' in content


def test_partials_do_not_extend_base():
    """Every templates/**/_*.html is scanned; none may extend base.html — a partial that does
    would swap a whole page into whatever element an HTMX response targets.
    """
    partial_paths = list(TEMPLATE_ROOT.rglob("_*.html"))
    assert partial_paths, "no partial templates found under templates/ — the glob is broken"

    offenders = [
        str(path.relative_to(TEMPLATE_ROOT))
        for path in partial_paths
        if EXTENDS_BASE_RE.search(path.read_text())
    ]

    assert offenders == []


def test_home_requires_login(client):
    response = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_home_dashboard_cards(client, user_factory):
    """The sections that exist (recipes, dishes, books — tasks 04-06) are real links on the
    home dashboard; lists and planner (07-08) are still non-interactive "Coming soon." cards.
    """
    client.force_login(user_factory())

    content = client.get(reverse("core:home")).content.decode()

    for path in ("/recipes/", "/dishes/", "/books/"):
        assert f'href="{path}"' in content
    assert content.count("Coming soon.") == 2
    # The live sections must not be dressed as "coming soon"
    coming_soon_block = content.split("Lists")[-1]
    assert "Recipes" not in coming_soon_block and "Dishes" not in coming_soon_block


def test_auth_screens_render_as_complete_documents(client, user_factory):
    """login.html, password_change.html and profile.html all extend base.html, but nothing
    proved any of them renders as a complete document via the plain test client the way
    test_page_works_without_htmx does for core:home (Plan/02-UI-Shell/.review-findings.md,
    finding 2). test_a11y.py's lang/viewport checks and test_base_template_renders's nav/
    messages check only ever look at a fragment of each response, not the document shape.
    """
    user = user_factory()

    login_response = client.get(reverse("accounts:login"))

    client.force_login(user)
    password_change_response = client.get(reverse("accounts:password_change"))
    profile_response = client.get(reverse("accounts:profile"))

    for response in (login_response, password_change_response, profile_response):
        assert response.status_code == 200
        content = response.content.decode()
        assert content.strip().startswith("<!DOCTYPE html>")
        assert "<html" in content
        assert "</html>" in content
        assert "<body" in content
        assert "</body>" in content


def test_login_failure_error_uses_alert_component(client, user_factory):
    """H3 regression: components.css's error-text rule is scoped `.field .field-errors`, but
    login.html's non_field_errors block rendered a bare `<ul class="field-errors">` outside
    any `.field` wrapper, so it never matched and rendered as an unstyled default bullet
    list. It must use the `.alert.alert-error` component instead, matching the styling flash
    messages already use elsewhere (see templates/_partials/_messages.html).
    """
    user = user_factory()

    response = client.post(
        reverse("accounts:login"),
        {"username": user.username, "password": "not-the-real-password"},
    )
    content = response.content.decode()

    assert response.status_code == 200
    assert 'class="alert alert-error"' in content
    assert "field-errors" not in content


def test_password_change_non_field_errors_use_alert_component(client, user_factory):
    """F2 (pass 6): password_change.html's non_field_errors block had the same bare
    `<ul class="field-errors">` pattern H3 fixed on login.html, sitting outside any `.field`
    wrapper so components.css's `.field .field-errors` rule never matched. Django's real
    PasswordChangeForm never actually raises a non-field error (every validation failure it
    produces is attached to old_password or new_password2), so the bug was unreachable through
    ordinary form input — force one via a patched `clean()` to drive the real view and prove
    the block now renders through `.alert.alert-error` like login.html does.
    """
    user = user_factory()
    client.force_login(user)

    def _clean_with_non_field_error(self):
        raise ValidationError("Something went wrong.")

    with patch.object(TempPasswordAwarePasswordChangeForm, "clean", _clean_with_non_field_error):
        response = client.post(
            reverse("accounts:password_change"),
            {
                "old_password": DEFAULT_TEST_PASSWORD,
                "new_password1": "irrelevant-new-pw-123",
                "new_password2": "irrelevant-new-pw-123",
            },
        )
    content = response.content.decode()

    assert response.status_code == 200
    assert 'class="alert alert-error"' in content
    # No per-field errors should be present alongside the injected non-field error -- the
    # correct old_password and matching new passwords mean clean_old_password/
    # clean_new_password2 both pass, so any "field-errors" markup left would prove the
    # non-field block regressed back to the bare <ul class="field-errors"> pattern.
    assert "field-errors" not in content


def test_error_templates_render():
    """403, 404 and 500 must not crash when rendered with zero context and no request — the
    real invocation Django's own server_error view uses for 500.html in production (see
    core/tests/test_a11y.py and design.md's "500 must not depend on a context processor").
    """
    for name in ("403.html", "404.html", "500.html"):
        rendered = render_to_string(name)
        assert rendered.strip(), f"{name} rendered empty"
