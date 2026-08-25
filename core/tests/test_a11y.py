"""Baseline accessibility contracts — see Plan/02-UI-Shell/test-plan.md, "Accessibility".

Cheap to enforce at the shell, expensive to retrofit later (design.md, "Accessibility").
"""

import re

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

INPUT_TAG_RE = re.compile(r"<input\b[^>]*>")
LABEL_FOR_RE = re.compile(r"""<label\b[^>]*\bfor=["\']([^"\']+)["\']""")
ATTR_RE = re.compile(r"""([\w-]+)=["\']([^"\']*)["\']""")
SUMMARY_RE = re.compile(r"<summary\b[^>]*>(.*?)</summary>", re.DOTALL)
ARIA_DESCRIBEDBY_RE = re.compile(r'aria-describedby="([^"]*)"')
ID_RE = re.compile(r'id="([^"]*)"')


def _attrs(tag: str) -> dict[str, str]:
    return dict(ATTR_RE.findall(tag))


def _visible_input_ids(html: str) -> list[str]:
    """IDs of every rendered <input> that isn't type="hidden" — a hidden field (e.g. login's
    `next`) has no visible control and so needs no label.
    """
    ids = []
    for tag in INPUT_TAG_RE.findall(html):
        attrs = _attrs(tag)
        if attrs.get("type") == "hidden":
            continue
        if "id" in attrs:
            ids.append(attrs["id"])
    return ids


def _assert_all_inputs_labelled(html: str) -> None:
    input_ids = _visible_input_ids(html)
    assert input_ids, "no visible <input> elements found — the scan matched nothing"

    label_targets = set(LABEL_FOR_RE.findall(html))
    missing = [input_id for input_id in input_ids if input_id not in label_targets]

    assert missing == [], f"inputs with no associated <label for=...>: {missing}"


def test_page_has_lang_and_title(client):
    response = client.get(reverse("accounts:login"))
    content = response.content.decode()

    assert '<html lang="en">' in content
    title_match = re.search(r"<title>(.*?)</title>", content, re.DOTALL)
    assert title_match is not None
    assert title_match.group(1).strip()


def test_viewport_meta_present(client):
    response = client.get(reverse("accounts:login"))
    content = response.content.decode()

    assert re.search(r'<meta\s+name="viewport"\s+content="[^"]*width=device-width', content)


def test_form_inputs_have_labels(client, user_factory):
    login_response = client.get(reverse("accounts:login"))
    _assert_all_inputs_labelled(login_response.content.decode())

    user = user_factory()
    client.force_login(user)
    change_response = client.get(reverse("accounts:password_change"))
    _assert_all_inputs_labelled(change_response.content.decode())


def _describedby_targets_resolve(html: str) -> int:
    """Asserts every aria-describedby value on the page is a space-separated list of ids
    that actually exist somewhere in the document, and returns how many were found -- Django
    5.2 emits `{{ field.auto_id }}_helptext` and `{{ field.auto_id }}_error` itself, so the
    partial supplying those ids just has to agree.
    """
    ids_present = set(ID_RE.findall(html))
    describedby_values = ARIA_DESCRIBEDBY_RE.findall(html)

    for value in describedby_values:
        for target_id in value.split():
            assert target_id in ids_present, (
                f"aria-describedby target {target_id!r} has no matching id in the document"
            )

    return len(describedby_values)


def test_aria_describedby_targets_resolve_to_real_ids(client, user_factory):
    """C2 regression: _form_field.html must emit the same ids Django's own aria-describedby
    attribute points at, for both the help-text and the error case. Login's fields carry
    neither help text nor per-field errors (a bad login is a non-field error), so it
    contributes no aria-describedby of its own -- it's included so a regression that adds
    one there is still caught, but the non-vacuousness check below relies on password_change.
    """
    login_response = client.get(reverse("accounts:login"))
    found = _describedby_targets_resolve(login_response.content.decode())

    user = user_factory()
    client.force_login(user)

    change_response = client.get(reverse("accounts:password_change"))
    found += _describedby_targets_resolve(change_response.content.decode())

    # An empty POST binds the form with errors, which is the only way Django emits the
    # `_error` half of aria-describedby -- the GET above only exercises `_helptext`.
    invalid_response = client.post(reverse("accounts:password_change"), {})
    found += _describedby_targets_resolve(invalid_response.content.decode())

    assert found > 0, "no aria-describedby attributes found anywhere -- the scan matched nothing"


def test_anonymous_login_page_has_no_authenticated_nav_chrome(client):
    """S2 regression: base.html includes _partials/_nav.html unconditionally, so anonymous
    pages (login, 429, 403, 404) must not render the Profile link, Log out form, or an
    interactive <summary> with no accessible name -- see Plan/02-UI-Shell/.review-findings.md.
    """
    response = client.get(reverse("accounts:login"))
    content = response.content.decode()

    assert reverse("accounts:profile") not in content
    assert reverse("accounts:logout") not in content
    assert "Log out" not in content


def test_every_rendered_summary_has_non_empty_text(client, user_factory):
    """Every <summary> on both an anonymous and an authenticated page must carry visible,
    non-empty text -- an interactive disclosure control with no accessible name is a
    blocking a11y defect (S2), not a styling nit.
    """
    anonymous_content = client.get(reverse("accounts:login")).content.decode()
    assert SUMMARY_RE.findall(anonymous_content) == []

    user = user_factory()
    client.force_login(user)
    authenticated_content = client.get(reverse("accounts:profile")).content.decode()
    summaries = SUMMARY_RE.findall(authenticated_content)
    assert summaries, "no <summary> elements found -- the scan matched nothing"
    for summary_html in summaries:
        assert re.sub(r"<[^>]+>", "", summary_html).strip()
