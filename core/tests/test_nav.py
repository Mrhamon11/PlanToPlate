"""_partials/_nav.html — see Plan/02-UI-Shell/test-plan.md, "Navigation"."""

import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _render_nav(user, nav_active=None):
    return render_to_string("_partials/_nav.html", {"user": user, "nav_active": nav_active})


def test_admin_link_hidden_for_regular_user(user_factory):
    user = user_factory(is_staff=False)

    html = _render_nav(user)

    assert reverse("admin:index") not in html


def test_admin_link_shown_for_staff(user_factory):
    user = user_factory(is_staff=True)

    html = _render_nav(user)

    assert reverse("admin:index") in html


def test_nav_marks_current_section(user_factory):
    user = user_factory()

    html = _render_nav(user, nav_active="recipes")

    assert re.search(r'href="/recipes/"\s+aria-current="page"', html)
    # A section that is not current must never carry aria-current itself.
    assert not re.search(r'href="/dishes/"\s+aria-current="page"', html)
    assert not re.search(r'href="/planner/"\s+aria-current="page"', html)


def test_nav_marks_nothing_current_when_unset(user_factory):
    user = user_factory()

    html = _render_nav(user)

    assert 'aria-current="page"' not in html


def test_admin_link_is_never_boosted(user_factory):
    """H1 regression: hx-boost="true" on the ancestor <nav> boosts every descendant link,
    including both Admin links (desktop nav-top and the mobile "More" overflow panel). A
    boosted request swaps only <body>, so admin's own <head> -- a separate template
    hierarchy that never extends base.html -- and its stylesheet never load. Both Admin
    links must opt out with hx-boost="false" so they always do a full navigation.
    """
    user = user_factory(is_staff=True)

    html = _render_nav(user)

    admin_url = reverse("admin:index")
    admin_links = re.findall(rf'<a href="{re.escape(admin_url)}"[^>]*>', html)

    assert len(admin_links) == 2, f"expected 2 Admin links (top + bottom bar), found {admin_links}"
    assert all('hx-boost="false"' in link for link in admin_links)


def test_bottom_bar_has_home_link(user_factory):
    """H2 regression: .nav-bottom had no way back to / — only the primary section links and
    the authenticated-only "More" overflow menu. A Home tab must be reachable from the
    bottom bar for both anonymous and authenticated visitors, with no JavaScript required.
    """
    home_url = reverse("core:home")

    for user in (AnonymousUser(), user_factory()):
        html = _render_nav(user)
        bottom_bar = html.split('<nav class="nav-bottom"', 1)[1]
        assert f'href="{home_url}"' in bottom_bar


def test_home_view_marks_home_tab_current(client, user_factory):
    """F1 (pass 6): HomeView never set nav_active, so the Home tab added in pass 5 could never
    render aria-current="page" even when the user is actually on /. Drive the real view rather
    than _render_nav directly -- this bug was in HomeView's context, not in the partial.
    """
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("core:home"))
    content = response.content.decode()

    home_url = reverse("core:home")
    assert re.search(rf'href="{re.escape(home_url)}"\s+aria-current="page"', content)


def test_nav_hides_authenticated_chrome_for_anonymous_user():
    """S2 regression: an anonymous visitor must not see the Profile link, Log out form, or
    the profile/overflow <details> menus at all -- those destinations only make sense for a
    signed-in user, and the desktop menu's <summary> renders with no accessible name (just
    {{ user.username }}) when user is AnonymousUser.
    """
    html = _render_nav(AnonymousUser())

    assert reverse("accounts:profile") not in html
    assert reverse("accounts:logout") not in html
    assert "<details" not in html
    assert "<summary" not in html
