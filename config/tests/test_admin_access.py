"""Access control on the custom ``AdminSite`` (task 09.1).

``PlanToPlateAdminSite.has_permission`` tightens the stock ``is_active and is_staff`` check
with "and not ``must_change_password``". The gate lives on the ``AdminSite`` itself, so a
single forgotten per-view check cannot expose the admin (``design.md``, "Security notes").
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from config.admin import PlanToPlateAdminSite

pytestmark = pytest.mark.django_db

#: The apps whose models this project owns and must register. Excludes Django's own apps,
#: third-party apps, and ``core_test_fixtures`` (throwaway models, test DB only).
PROJECT_APP_LABELS = {
    "accounts",
    "catalog",
    "core",
    "recipes",
    "meals",
    "lists",
    "planner",
}


def _has_permission(user) -> bool:
    request = RequestFactory().get("/admin/")
    request.user = user
    return PlanToPlateAdminSite().has_permission(request)


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert reverse("admin:login") in response.url


def test_regular_user_denied(client, user_factory):
    client.force_login(user_factory(username="regular", is_staff=False))

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert reverse("admin:login") in response.url
    assert _has_permission(user_factory(username="regular2", is_staff=False)) is False


def test_staff_user_allowed(client, user_factory):
    staff = user_factory(username="staffer", is_staff=True, is_superuser=True)
    client.force_login(staff)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert _has_permission(staff) is True


def test_inactive_staff_denied(user_factory):
    inactive = user_factory(username="ex-staff", is_staff=True, is_active=False)

    assert _has_permission(inactive) is False


def test_staff_with_pending_password_change_denied(client, user_factory):
    """An admin mid-forced-reset administers nothing — both at the ``has_permission`` gate and,
    one layer earlier, at ``ForcePasswordChangeMiddleware``.
    """
    stale = user_factory(username="stale-admin", is_staff=True, must_change_password=True)

    assert _has_permission(stale) is False

    client.force_login(stale)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change")


def test_every_model_registered():
    """Introspect every project app's concrete models; each must have a ``ModelAdmin``.

    Catches the model a later task adds and nobody registers (``test-plan.md``).
    """
    unregistered = []
    for app_config in apps.get_app_configs():
        if app_config.label not in PROJECT_APP_LABELS:
            continue
        for model in app_config.get_models():
            if model._meta.proxy:
                continue
            if model not in admin.site._registry:
                unregistered.append(model._meta.label)

    assert not unregistered, f"models with no ModelAdmin: {sorted(unregistered)}"
