"""Render tests for the ownership/sharing partials (03.10, tasks.md):
``templates/_partials/_ownership_badge.html``, ``_copy_button.html``, ``_share_modal.html``,
``_copied_from.html``.

None of these are included anywhere else in the test suite -- `core/tests/views.py`'s dummy
views render `core_test_fixtures/dummy_*.html`, not these -- so the conditional branching each
partial documents in its own header comment (the badge's is_system / mine / public / shared-by-
elimination branches, the copy button's owner-vs-not gate, the share modal's visibility radios
and current-shares list) was previously unverified: a typo in any of those conditions would
render silently wrong and nothing would fail. Exercised with `render_to_string` directly,
following the pattern in `core/tests/test_templates.py`, against the throwaway `DummyOwned`
fixture used throughout task 03's own suite.
"""

from __future__ import annotations

import re

import pytest
from django.template.loader import render_to_string

from core.models import Visibility

pytestmark = pytest.mark.django_db


def _is_radio_checked(rendered: str, value: str) -> bool:
    match = re.search(rf'name="visibility" value="{value}"\s*(checked)?>', rendered)
    assert match, f"no visibility radio found for {value!r} in:\n{rendered}"
    return match.group(1) == "checked"


# --- _ownership_badge.html ---------------------------------------------------------------------


def test_ownership_badge_shows_mine_for_owner(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    rendered = render_to_string("_partials/_ownership_badge.html", {"object": obj, "user": alice})

    assert 'class="badge badge-mine"' in rendered
    assert "Mine" in rendered


def test_ownership_badge_shows_shared_for_non_owner_with_a_grant(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    rendered = render_to_string("_partials/_ownership_badge.html", {"object": obj, "user": bob})

    assert 'class="badge"' in rendered
    assert "Shared with me" in rendered
    assert "badge-mine" not in rendered
    assert "badge-public" not in rendered
    assert "badge-system" not in rendered


def test_ownership_badge_shows_public_for_non_owner_of_a_public_object(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)

    rendered = render_to_string("_partials/_ownership_badge.html", {"object": obj, "user": carol})

    assert 'class="badge badge-public"' in rendered
    assert "Public" in rendered


def test_ownership_badge_shows_built_in_for_system_object(carol, make_dummy):
    obj = make_dummy(owner=None, is_system=True)

    rendered = render_to_string("_partials/_ownership_badge.html", {"object": obj, "user": carol})

    assert 'class="badge badge-system"' in rendered
    assert "Built-in" in rendered


def test_ownership_badge_prefers_system_over_owner(alice, make_dummy):
    """is_system is checked first -- even the object's own "owner" (there isn't one, since
    owner is NULL on a system row per the owner-XOR-system constraint, but the branch order
    itself is what's under test here) must never fall through to the "Mine" branch.
    """
    obj = make_dummy(owner=None, is_system=True)

    rendered = render_to_string("_partials/_ownership_badge.html", {"object": obj, "user": alice})

    assert "Built-in" in rendered
    assert "Mine" not in rendered


# --- _copy_button.html ---------------------------------------------------------------------


def test_copy_button_hidden_for_owner(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    rendered = render_to_string(
        "_partials/_copy_button.html", {"object": obj, "user": alice, "copy_url": "/dummy/1/copy/"}
    )

    assert rendered.strip() == ""
    assert "Copy to my collection" not in rendered


def test_copy_button_shown_for_non_owner_of_a_shared_object(alice, bob, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)
    copy_url = f"/dummy/{obj.pk}/copy/"

    rendered = render_to_string(
        "_partials/_copy_button.html", {"object": obj, "user": bob, "copy_url": copy_url}
    )

    assert "Copy to my collection" in rendered
    assert f'action="{copy_url}"' in rendered


def test_copy_button_shown_for_public_object(alice, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PUBLIC)
    copy_url = f"/dummy/{obj.pk}/copy/"

    rendered = render_to_string(
        "_partials/_copy_button.html", {"object": obj, "user": carol, "copy_url": copy_url}
    )

    assert "Copy to my collection" in rendered
    assert f'action="{copy_url}"' in rendered


def test_copy_button_shown_for_system_object(carol, make_dummy):
    obj = make_dummy(owner=None, is_system=True)
    copy_url = f"/dummy/{obj.pk}/copy/"

    rendered = render_to_string(
        "_partials/_copy_button.html", {"object": obj, "user": carol, "copy_url": copy_url}
    )

    assert "Copy to my collection" in rendered
    assert f'action="{copy_url}"' in rendered


# --- _share_modal.html ---------------------------------------------------------------------


def _share_modal_context(obj, **extra):
    context = {
        "object": obj,
        "user": obj.owner,
        "share_url": f"/dummy/{obj.pk}/share/",
        "unshare_url": f"/dummy/{obj.pk}/unshare/",
        "shareable_users": [],
        "cancel_url": "/dummy-html/",
    }
    context.update(extra)
    return context


@pytest.mark.parametrize("visibility", [Visibility.PRIVATE, Visibility.SHARED, Visibility.PUBLIC])
def test_share_modal_checks_only_the_radio_matching_current_visibility(
    alice, make_dummy, visibility
):
    obj = make_dummy(owner=alice, visibility=visibility)

    rendered = render_to_string("_partials/_share_modal.html", _share_modal_context(obj))

    for candidate in (Visibility.PRIVATE, Visibility.SHARED, Visibility.PUBLIC):
        assert _is_radio_checked(rendered, candidate) is (candidate == visibility)


def test_share_modal_lists_shareable_users_in_the_multiselect(alice, bob, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    rendered = render_to_string(
        "_partials/_share_modal.html", _share_modal_context(obj, shareable_users=[bob, carol])
    )

    assert f'<option value="{bob.pk}">{bob.username}</option>' in rendered
    assert f'<option value="{carol.pk}">{carol.username}</option>' in rendered


def test_share_modal_shows_empty_state_with_no_current_shares(alice, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.PRIVATE)

    rendered = render_to_string("_partials/_share_modal.html", _share_modal_context(obj))

    assert "Not shared with anyone yet." in rendered
    assert "share-list-item" not in rendered


def test_share_modal_lists_current_shares_with_revoke_buttons(alice, bob, carol, make_dummy):
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob, carol)

    rendered = render_to_string("_partials/_share_modal.html", _share_modal_context(obj))

    assert "Not shared with anyone yet." not in rendered
    assert rendered.count('class="share-list-item"') == 2
    assert f"Revoke access for {bob.username}" in rendered
    assert f"Revoke access for {carol.username}" in rendered
    assert f'<input type="hidden" name="users" value="{bob.pk}">' in rendered
    assert f'<input type="hidden" name="users" value="{carol.pk}">' in rendered


# --- the audience-list leak this modal must never reopen (03.8a rework, security finding 1) ---


def test_share_modal_renders_nothing_for_a_non_owner(alice, bob, carol, make_dummy):
    """The regression this guard exists for: a caller that includes the modal for a non-owner
    (unconditionally, or trusting UI/CSS to hide it) must not leak the sharee list -- the same
    data the API's /shares/ action is IsOwner-only about (design.md: "the audience list is
    itself sensitive"). Sharing the object with bob (so it's visible to him, and shared with
    someone else -- carol) proves this isn't just "empty because there's nothing to show".
    """
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob, carol)

    rendered = render_to_string("_partials/_share_modal.html", _share_modal_context(obj, user=bob))

    assert rendered.strip() == ""
    assert carol.username not in rendered
    assert bob.username not in rendered


def test_share_modal_renders_nothing_for_an_anonymous_user(alice, bob, make_dummy):
    """Same leak, reached through a missing/anonymous `user` in context instead of a logged-in
    non-owner -- Django's default `string_if_invalid` (`""`) must not make the ownership check
    accidentally pass.
    """
    from django.contrib.auth.models import AnonymousUser

    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    rendered = render_to_string(
        "_partials/_share_modal.html", _share_modal_context(obj, user=AnonymousUser())
    )

    assert rendered.strip() == ""
    assert bob.username not in rendered


def test_share_modal_renders_for_the_real_owner(alice, bob, make_dummy):
    """Non-vacuousness: the same object, viewed by its actual owner, still renders the full
    modal -- proving the two tests above are the gate firing, not the partial being broken.
    """
    obj = make_dummy(owner=alice, visibility=Visibility.SHARED)
    obj.shared_with.add(bob)

    rendered = render_to_string(
        "_partials/_share_modal.html", _share_modal_context(obj, user=alice)
    )

    assert rendered.strip() != ""
    assert bob.username in rendered


# --- _copied_from.html ---------------------------------------------------------------------


def test_copied_from_partial_shows_provenance_line(alice, bob, make_dummy):
    original = make_dummy(owner=alice, name="Roast Chicken")
    copy = make_dummy(owner=bob, name="Roast Chicken", copied_from=original)

    rendered = render_to_string("_partials/_copied_from.html", {"object": copy})

    assert f"Copied from {alice.username}" in rendered
    assert "Roast Chicken" in rendered


def test_copied_from_partial_shows_provenance_line_for_a_copy_of_a_system_object(bob, make_dummy):
    """Iteration-3 review blocking finding 3: a system original has `owner = NULL` (the
    owner-XOR-system constraint), and `core/services/copying.py` sets `copied_from`
    unconditionally, including when copying a built-in -- design.md's own named use case
    (copying a seeded ingredient, e.g. "Sea Salt", to make an editable version). Pre-fix this
    rendered `Copied from &rsquo;s Sea Salt.` -- a raw HTML entity with no owner name.
    """
    original = make_dummy(owner=None, is_system=True, name="Sea Salt")
    copy = make_dummy(owner=bob, name="Sea Salt", copied_from=original)

    rendered = render_to_string("_partials/_copied_from.html", {"object": copy})

    assert "Copied from the built-in" in rendered
    assert "Sea Salt" in rendered
    assert "&rsquo;s" not in rendered
    assert "Copied from &rsquo;s" not in rendered


def test_copied_from_partial_renders_nothing_for_a_non_copy(alice, make_dummy):
    obj = make_dummy(owner=alice)

    rendered = render_to_string("_partials/_copied_from.html", {"object": obj})

    assert rendered.strip() == ""


def test_copied_from_partial_renders_nothing_once_the_original_is_deleted(alice, bob, make_dummy):
    """copied_from is SET_NULL (design.md, "Deleting a shared object") -- once the original is
    gone the provenance line must disappear too, not dangle on a null pointer.
    """
    original = make_dummy(owner=alice, name="Roast Chicken")
    copy = make_dummy(owner=bob, name="Roast Chicken", copied_from=original)
    original.delete()
    copy.refresh_from_db()

    rendered = render_to_string("_partials/_copied_from.html", {"object": copy})

    assert rendered.strip() == ""
