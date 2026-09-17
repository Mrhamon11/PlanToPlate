"""Admin security posture (task 09.1–09.2, 09.11).

Covers ``Plan/09-Admin-Control-Center/test-plan.md``'s "Security" table in full: no arbitrary
SQL endpoint, custom actions are POST-only, CSRF is enforced on the custom admin forms, the
import upload rejects a non-JSON file, and no admin URL is reachable by a non-staff user.
"""

from __future__ import annotations

import json

import pytest
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client
from django.urls import NoReverseMatch, get_resolver, reverse

from accounts.models import User
from recipes.models import Recipe

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(user_factory):
    client = Client()
    client.force_login(user_factory(username="securitystaff", is_staff=True, is_superuser=True))
    return client


def _all_admin_url_names() -> list[str]:
    resolver = get_resolver()
    admin_ns = resolver.namespace_dict.get("admin")
    if admin_ns is None:
        return []
    _, admin_resolver = admin_ns
    return list(admin_resolver.reverse_dict.keys())


# --- no raw SQL -------------------------------------------------------------------------------


def test_no_raw_sql_endpoint_exists():
    """A raw-SQL console is deliberately not built — it would be a remote code execution
    primitive on a home server (``design.md``, "Security notes").
    """
    forbidden = ("sql", "query", "raw", "execute", "shell", "console", "dbshell")

    for name in _all_admin_url_names():
        lowered = str(name).lower()
        assert not any(token in lowered for token in forbidden), name


# --- POST-only custom actions --------------------------------------------------------------


def test_admin_actions_require_post(staff_client, user_factory):
    """A custom admin action does nothing when reached with a GET query string — Django's
    action machinery only runs the callable on POST.
    """
    target = user_factory(username="getpromote", is_staff=False)
    changelist = reverse("admin:accounts_user_changelist")

    get_response = staff_client.get(
        changelist, {"action": "grant_admin", "_selected_action": str(target.pk)}
    )
    assert get_response.status_code in (200, 302)
    target.refresh_from_db()
    assert target.is_staff is False

    staff_client.post(changelist, {"action": "grant_admin", "_selected_action": [str(target.pk)]})
    target.refresh_from_db()
    assert target.is_staff is True


# --- CSRF ----------------------------------------------------------------------------------


def test_admin_csrf_enforced(user_factory):
    """The custom create-user form is CSRF-protected like every admin view — a POST with no
    token is refused.
    """
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user_factory(username="csrfstaff", is_staff=True, is_superuser=True))

    response = csrf_client.post(
        reverse("admin:accounts_user_create"),
        {"username": "viacsrf", "email": "", "first_name": "", "last_name": ""},
    )

    assert response.status_code == 403
    assert not User.objects.filter(username="viacsrf").exists()


def test_import_upload_csrf_enforced(user_factory):
    """The JSON-import upload is CSRF-protected like every admin view (``admin_view`` +
    ``{% csrf_token %}``). A regression dropping it on that view would otherwise pass silently
    — pin it: a valid payload POSTed with no token is refused before ``run_import`` runs.
    """
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user_factory(username="csrfimport", is_staff=True, is_superuser=True))
    owner = user_factory(username="csrfimportowner")
    payload = SimpleUploadedFile(
        "import.json",
        json.dumps({"version": 1, "ingredients": [], "recipes": [], "dishes": []}).encode(),
        content_type="application/json",
    )

    response = csrf_client.post(
        reverse("admin:core_import_json"),
        {"file": payload, "owner": str(owner.pk), "mode": "skip-existing", "dry_run": "on"},
    )

    assert response.status_code == 403
    assert not Recipe.objects.filter(owner=owner).exists()


# --- import upload rejects non-JSON ------------------------------------------------------------


def test_import_upload_rejects_non_json(staff_client, user_factory):
    owner = user_factory(username="importee")
    upload = SimpleUploadedFile("notes.txt", b"this is not json at all", content_type="text/plain")

    response = staff_client.post(
        reverse("admin:core_import_json"),
        {"file": upload, "owner": str(owner.pk), "mode": "skip-existing"},
    )

    assert response.status_code == 200
    assert b"malformed JSON" in response.content
    assert not Recipe.objects.filter(owner=owner).exists()


def test_import_upload_surfaces_unexpected_error_as_problem(
    staff_client, user_factory, monkeypatch
):
    """A write ``validate`` did not anticipate (an ``IntegrityError`` from deep in ``execute``)
    renders as a problem-list entry, never a 500 (09 rework NB4).
    """
    import core.admin as core_admin

    def boom(**kwargs):
        raise IntegrityError("simulated constraint violation")

    monkeypatch.setattr(core_admin, "run_import", boom)
    owner = user_factory(username="importboom")
    upload = SimpleUploadedFile(
        "import.json",
        json.dumps({"version": 1, "ingredients": [], "recipes": [], "dishes": []}).encode(),
        content_type="application/json",
    )

    response = staff_client.post(
        reverse("admin:core_import_json"),
        {"file": upload, "owner": str(owner.pk), "mode": "skip-existing"},
    )

    assert response.status_code == 200
    assert b"could not be applied" in response.content


# --- D29: the DRF token back door is closed -----------------------------------------------


def test_token_proxy_not_registered_in_admin():
    """``rest_framework.authtoken.TokenProxy`` is unregistered (``config/apps.py``, D29): its
    add form minted a DRF token for any user with no audit trail and no revocation semantics.
    """
    from rest_framework.authtoken.models import TokenProxy

    assert TokenProxy not in admin.site._registry
    with pytest.raises(NoReverseMatch):
        reverse("admin:authtoken_tokenproxy_add")


# --- non-staff cannot reach any admin URL --------------------------------------------------


def test_admin_urls_not_guessable_by_regular_user(client, user_factory):
    """Every admin changelist / add URL returns 403 or a redirect to the admin login for a
    non-staff authenticated user — never 200.
    """
    client.force_login(user_factory(username="nosy", is_staff=False))
    victim = user_factory(username="victim")

    checked = 0
    for model in admin.site._registry:
        opts = model._meta
        for suffix in ("changelist", "add"):
            url = reverse(f"admin:{opts.app_label}_{opts.model_name}_{suffix}")
            response = client.get(url)
            assert response.status_code in (302, 403), (url, response.status_code)
            if response.status_code == 302:
                assert reverse("admin:login") in response.url
            checked += 1

    # The custom user-provisioning and (overridden) delete views are ``admin_view``-gated
    # like the rest — pin that at these URLs so a regression that mounts one raw cannot pass.
    extra_urls = [
        reverse("admin:accounts_user_create"),
        reverse("admin:accounts_user_delete", args=[victim.pk]),
        reverse("admin:core_import_json"),
    ]
    for url in extra_urls:
        response = client.get(url)
        assert response.status_code in (302, 403), (url, response.status_code)
        if response.status_code == 302:
            assert reverse("admin:login") in response.url
        checked += 1

    assert checked > 0


def test_admin_index_is_bounced_for_anonymous(client):
    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert reverse("admin:login") in response.url
