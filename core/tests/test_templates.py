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
    """Every section (recipes, dishes, books, lists, planner — tasks 04-08) is a real link on
    the home dashboard; no "Coming soon." placeholder card remains.
    """
    client.force_login(user_factory())

    content = client.get(reverse("core:home")).content.decode()

    for path in ("/recipes/", "/dishes/", "/books/", "/lists/", "/planner/"):
        assert f'href="{path}"' in content
    assert "Coming soon." not in content


def test_new_user_home_is_not_blank(client, carol):
    """A brand-new user with no data gets the five section links and one "get started" line —
    never an empty panel box, never a page that reads as broken (12.12).

    The two flagship panels still render (as a one-line CTA), because "what am I cooking, and
    what do I need to buy?" is the question the page exists to answer even before there is an
    answer (blocking finding #1); the other five secondary panels stay hidden when empty.
    """
    client.force_login(carol)

    content = client.get(reverse("core:home")).content.decode()

    assert "add your first recipe" in content
    for path in ("/recipes/", "/dishes/", "/books/", "/lists/", "/planner/"):
        assert f'href="{path}"' in content
    # The flagship panels render their empty-state CTA.
    assert "This week" in content
    assert "Shopping" in content
    assert "No plan yet" in content
    assert "Nothing on the list" in content
    generate_url = reverse("planner:plan-generate")
    assert f'href="{generate_url}"' in content
    # No secondary panel with nothing to say is rendered.
    for heading in (
        "Recently viewed",
        "Favourites",
        "Shared with you",
        "Public from others",
        "What should I make?",
    ):
        assert heading not in content


def test_panels_render_without_htmx(
    client,
    alice,
    bob,
    make_plan,
    add_entry,
    dish_with_component,
    make_list,
    make_recipe,
    make_ingredient,
    gram,
    set_favourite,
    share_with,
):
    """The plain test client — no HX-Request header — gets every panel's content in the first
    response. No hx-trigger="load" anywhere (the task 02 no-JS rule): the dashboard must be
    complete without JavaScript.
    """
    import datetime

    from django.utils import timezone

    from core.services.recent import record_view
    from lists.models import ListItem, ListKind
    from planner.models import MealSlot

    today = timezone.localdate()
    plan = make_plan(owner=alice, start_date=today - datetime.timedelta(days=1), days=7)
    add_entry(
        plan, day_index=1, slot=MealSlot.DINNER, dish=dish_with_component("Tonight", owner=alice)
    )
    shopping = make_list(
        "Groceries", owner=alice, kind=ListKind.SHOPPING, is_default_shopping_list=True
    )
    ListItem.objects.create(list=shopping, position=0, text="milk")
    ListItem.objects.create(
        list=shopping,
        position=1,
        ingredient=make_ingredient("Carrots", owner=alice),
        quantity="500",
        unit=gram,
    )
    recipe = make_recipe("Viewed recipe", owner=alice)
    record_view(alice, recipe)
    set_favourite(alice, recipe)
    share_with(make_recipe("From bob", owner=bob), alice)

    from core.models import Visibility

    public = make_recipe("Bob public recipe", owner=bob)
    public.visibility = Visibility.PUBLIC
    public.save(update_fields=["visibility"])

    client.force_login(alice)

    content = client.get(reverse("core:home")).content.decode()

    for heading in (
        "This week",
        "Shopping",
        "Recently viewed",
        "Favourites",
        "Shared with you",
        "Public from others",
        "What should I make?",
        "Browse",
    ):
        assert heading in content
    assert "Tonight" in content
    assert "Viewed recipe" in content
    assert "From bob" in content
    assert "Bob public recipe" in content
    # The shopping preview renders a real item's resolved label and quantity, not just counts.
    assert "Carrots" in content
    assert "500 g" in content
    assert 'hx-trigger="load"' not in content


def test_panel_fragment_endpoint_returns_partial(client, alice, make_recipe):
    """/dashboard/panel/<name>/ returns just the panel fragment — it does not extend
    base.html (12.13, an enhancement over already-rendered markup).
    """
    client.force_login(alice)

    response = client.get(reverse("core:dashboard-panel", args=["sections"]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<html" not in content
    assert "<nav" not in content
    assert 'id="panel-sections"' in content
    assert client.get(reverse("core:dashboard-panel", args=["nope"])).status_code == 404


def test_flagship_panel_fragments_are_null_safe_when_empty(client, alice):
    """`/dashboard/panel/this-week/` and `/shopping/` render their empty-state CTA rather than
    a degenerate header-only shell when the user has no plan / no list (12.13 sub-note, N5 —
    retired for these two by blocking finding #1).
    """
    client.force_login(alice)

    this_week = client.get(reverse("core:dashboard-panel", args=["this-week"]))
    shopping = client.get(reverse("core:dashboard-panel", args=["shopping"]))

    assert this_week.status_code == 200
    assert "No plan yet" in this_week.content.decode()
    assert shopping.status_code == 200
    assert "Nothing on the list" in shopping.content.decode()


def test_reroll_suggestion_swaps_panel(client, alice, dish_with_component):
    """The "what should I make?" re-roll names an explicit hx-target on the panel, not the
    triggering button (D39 / task 06's item-10 bug was exactly this omission).
    """
    dish_with_component("A dish", owner=alice)
    client.force_login(alice)

    content = client.get(reverse("core:home")).content.decode()

    panel_url = reverse("core:dashboard-panel", args=["suggestion"])
    assert f'hx-get="{panel_url}"' in content
    assert 'hx-target="#panel-suggestion"' in content


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
