import pytest
import yaml
from django.apps import apps
from django.core.management import call_command

EXPECTED_APP_LABELS = {"core", "accounts", "catalog", "recipes", "meals", "lists", "planner"}


def test_all_apps_installed():
    installed_labels = {config.label for config in apps.get_app_configs()}

    assert EXPECTED_APP_LABELS <= installed_labels


def test_no_pending_migrations(db):
    try:
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)
    except SystemExit as exc:
        pytest.fail(f"pending model changes with no migration (exit code {exc.code})")


def test_api_schema_renders(authenticated_client):
    response = authenticated_client.get("/api/schema/")

    assert response.status_code == 200
    schema = yaml.safe_load(response.content)
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "PlanToPlate API"
    assert "paths" in schema


def test_api_schema_requires_authentication(client):
    """drf-spectacular serves to AllowAny by default; that would publish the API shape.

    There is no anonymous access anywhere in this app (MILESTONES.md section 4), and the
    schema is not an exception. Deleting SERVE_PERMISSIONS from base.py fails here.
    """
    response = client.get("/api/schema/")

    assert response.status_code in (401, 403), response.status_code


def test_api_docs_requires_authentication(client):
    response = client.get("/api/docs/")

    assert response.status_code in (401, 403), response.status_code
