"""The project's custom ``AdminSite`` (task 09, ``design.md`` "Admin site configuration" and
"Admin dashboard").

``django.contrib.admin`` is customised, not replaced (D2). Three things differ from the stock
site:

1. Project branding (headers / titles).
2. ``has_permission`` also refuses a staff account that is inactive **or** still carrying a
   forced password change — "an admin who has not yet completed a forced password reset
   should not be administering anything" (``design.md``). The stock check is only
   ``is_active and is_staff``.
3. The index page carries an operational dashboard: user count, per-model object counts,
   recent signups and activity, the SQLite database + WAL file sizes, and quick links to the
   create-user and JSON-import pages.

Wired in through ``config.apps.PlanToPlateAdminConfig.default_site`` (Django's documented
"overriding the default admin site" hook), so ``django.contrib.admin.site`` — and therefore
every ``@admin.register`` decorator and ``admin.site.urls`` — transparently uses this class.
"""

from __future__ import annotations

from pathlib import Path

from django.contrib.admin import AdminSite
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.urls import path, reverse

#: Sections shown in the dashboard's object-count table, in order.
_COUNT_SECTION_ORDER = ("accounts", "catalog", "recipes", "meals", "lists", "planner", "core")


def _human_bytes(count: int) -> str:
    # ``float`` is fine here (CLAUDE.md §3 forbids it for measured quantities): this is
    # display-only byte-count formatting, never persisted, compared, or used in arithmetic
    # that feeds the data model. The exact byte counts stay as ``int`` in the returned dict.
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def database_file_sizes(connection=None) -> dict | None:
    """On-disk size of the SQLite database file and its write-ahead log.

    Returns ``{"database": <bytes>, "wal": <bytes>, "path": <str>, ...}`` for a file-backed
    SQLite database, or ``None`` for an in-memory database or a non-SQLite engine (Postgres
    tomorrow — the architecture rules require this to degrade, not crash). The WAL file is
    often absent (a checkpoint just ran, or WAL mode is off); that reports as ``0``.
    """
    from django.db import connections

    conn = connection or connections["default"]
    if conn.vendor != "sqlite":
        return None

    name = conn.settings_dict.get("NAME")
    if not name or str(name) == ":memory:" or "memory:" in str(name):
        return None

    db_path = Path(name)
    if not db_path.is_file():
        return None

    wal_path = db_path.with_name(db_path.name + "-wal")
    db_bytes = db_path.stat().st_size
    wal_bytes = wal_path.stat().st_size if wal_path.is_file() else 0
    return {
        "database": db_bytes,
        "wal": wal_bytes,
        "database_human": _human_bytes(db_bytes),
        "wal_human": _human_bytes(wal_bytes),
        "path": str(db_path),
    }


class PlanToPlateAdminSite(AdminSite):
    site_header = "PlanToPlate administration"
    site_title = "PlanToPlate admin"
    index_title = "Control center"
    index_template = "admin/plantoplate_index.html"

    def get_urls(self) -> list:
        """Add the bulk JSON import page (task 09.11). The view lives in ``core.admin`` — this
        just mounts it on the site and hands it the site instance for ``each_context``.
        """
        from core.admin import import_json_view

        custom = [
            path(
                "import-json/",
                self.admin_view(lambda request: import_json_view(request, self)),
                name="core_import_json",
            ),
        ]
        return custom + super().get_urls()

    def has_permission(self, request: HttpRequest) -> bool:
        """Stock ``is_active and is_staff``, plus: never while a forced password change is
        pending. ``must_change_password`` is an ``accounts.User`` field; ``getattr`` keeps this
        safe against ``AnonymousUser`` and any non-project user model.
        """
        user = request.user
        return bool(
            user.is_active and user.is_staff and not getattr(user, "must_change_password", False)
        )

    # -- dashboard (task 09.12) --------------------------------------------------------------

    def index(self, request: HttpRequest, extra_context: dict | None = None) -> TemplateResponse:
        extra_context = {**(extra_context or {}), "dashboard": self.dashboard_context()}
        return super().index(request, extra_context)

    def dashboard_context(self) -> dict:
        """Operational summary for the index page (``design.md``, "Admin dashboard").

        Kept off the template so the size/count logic is unit-testable and the template stays
        declarative.
        """
        from django.contrib import admin as django_admin
        from django.contrib.admin.models import LogEntry
        from django.contrib.auth import get_user_model

        user_model = get_user_model()

        models = sorted(
            django_admin.site._registry,
            key=lambda m: (
                _COUNT_SECTION_ORDER.index(m._meta.app_label)
                if m._meta.app_label in _COUNT_SECTION_ORDER
                else len(_COUNT_SECTION_ORDER),
                m._meta.verbose_name_plural.lower(),
            ),
        )
        model_counts = [
            {
                "label": model._meta.verbose_name_plural.title(),
                "app": model._meta.app_label,
                "count": model._default_manager.count(),
            }
            for model in models
        ]

        return {
            "user_count": user_model.objects.count(),
            "active_user_count": user_model.objects.filter(is_active=True).count(),
            "staff_count": user_model.objects.filter(is_staff=True, is_active=True).count(),
            "model_counts": model_counts,
            "recent_signups": list(user_model.objects.order_by("-date_joined")[:5]),
            "recent_activity": list(
                LogEntry.objects.select_related("content_type", "user").order_by("-action_time")[
                    :10
                ]
            ),
            "database": database_file_sizes(),
            "quick_links": [
                {"label": "Create a user", "url": reverse("admin:accounts_user_create")},
                {"label": "Import JSON", "url": reverse("admin:core_import_json")},
            ],
        }
