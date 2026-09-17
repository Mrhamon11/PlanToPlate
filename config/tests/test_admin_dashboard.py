"""The admin index dashboard (task 09.12, ``Plan/09-Admin-Control-Center/design.md``,
"Admin dashboard").

Covers the test-plan's "Dashboard" table: the page renders for staff, the object counts it
shows are accurate, and both the SQLite database file and its WAL file are reported.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse

from config.admin import database_file_sizes
from recipes.models import Recipe

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client, user_factory):
    client.force_login(user_factory(username="dashadmin", is_staff=True, is_superuser=True))
    return client


@pytest.fixture
def unit(db):
    from catalog.models import Dimension, Unit

    return Unit.objects.create(
        name="dashgram",
        abbrev="dg",
        plural="dashgrams",
        dimension=Dimension.MASS,
        to_base_factor=Decimal("1"),
    )


def test_dashboard_renders(staff_client):
    response = staff_client.get(reverse("admin:index"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Control center" in body
    assert "Object counts" in body
    assert "Quick actions" in body
    # Quick links resolve to the custom pages.
    assert reverse("admin:accounts_user_create") in body
    assert reverse("admin:core_import_json") in body


def test_counts_accurate(staff_client, user_factory, unit):
    for i in range(4):
        Recipe.objects.create(
            name=f"Dash recipe {i}",
            instructions="x",
            yield_quantity=Decimal("1"),
            yield_unit=unit,
            owner=user_factory(username=f"dashowner{i}"),
        )

    response = staff_client.get(reverse("admin:index"))
    dashboard = response.context["dashboard"]

    from accounts.models import User

    assert dashboard["user_count"] == User.objects.count()
    recipe_row = next(r for r in dashboard["model_counts"] if r["label"] == "Recipes")
    assert recipe_row["count"] == Recipe.objects.count() == 4


def test_db_size_reported(tmp_path):
    """The helper reports the database file size *and* the WAL file size — the operational
    signal that matters on SQLite.
    """
    db_path = tmp_path / "probe.sqlite3"
    # A real SQLite database file...
    sqlite3.connect(db_path).executescript("CREATE TABLE t (x); INSERT INTO t VALUES (1);")
    # ...and a companion write-ahead log with known contents.
    wal_path = db_path.with_name(db_path.name + "-wal")
    wal_path.write_bytes(b"\x00" * 8192)

    fake_connection = SimpleNamespace(vendor="sqlite", settings_dict={"NAME": str(db_path)})
    sizes = database_file_sizes(fake_connection)

    assert sizes is not None
    assert sizes["database"] == db_path.stat().st_size > 0
    assert sizes["wal"] == 8192
    assert sizes["path"] == str(db_path)
    assert sizes["database_human"] and sizes["wal_human"]


def test_db_size_wal_absent_reports_zero(tmp_path):
    """A missing ``-wal`` file (checkpoint just ran, or WAL mode off) reports as 0, not a crash."""
    db_path = tmp_path / "nowal.sqlite3"
    db_path.write_bytes(b"\x00" * 4096)

    sizes = database_file_sizes(
        SimpleNamespace(vendor="sqlite", settings_dict={"NAME": str(db_path)})
    )

    assert sizes is not None
    assert sizes["database"] == 4096
    assert sizes["wal"] == 0


def test_db_size_none_for_non_file_database():
    assert database_file_sizes(SimpleNamespace(vendor="postgresql", settings_dict={})) is None
    assert (
        database_file_sizes(SimpleNamespace(vendor="sqlite", settings_dict={"NAME": ":memory:"}))
        is None
    )
