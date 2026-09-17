"""``AppConfig`` for ``django.contrib.admin`` that points it at the project's custom
``AdminSite`` (``config.admin.PlanToPlateAdminSite``).

This is Django's documented way to override the default admin site: subclass ``AdminConfig``,
set ``default_site``, and list this config in ``INSTALLED_APPS`` in place of the bare
``"django.contrib.admin"``. ``AdminConfig`` keeps ``name = "django.contrib.admin"``, so the
admin app itself is unchanged — only the ``site`` singleton it exposes is swapped.

``ready()`` also unregisters ``authtoken.TokenProxy`` (D29): adding ``rest_framework.authtoken``
registers it in the admin, and ``/admin/authtoken/tokenproxy/add/`` then mints a DRF token for
any user with no audit trail and no token-revocation semantics. Nothing mints tokens through
the UI yet (D24), so the admin has no business doing it either; when a token-issuing flow is
needed it gets its own audited endpoint, not this back door.
"""

from __future__ import annotations

from django.contrib.admin.apps import AdminConfig


class PlanToPlateAdminConfig(AdminConfig):
    default_site = "config.admin.PlanToPlateAdminSite"

    def ready(self) -> None:
        super().ready()

        from django.contrib import admin
        from rest_framework.authtoken.models import TokenProxy

        try:
            admin.site.unregister(TokenProxy)
        except admin.sites.NotRegistered:
            pass
