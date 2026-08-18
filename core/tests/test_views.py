import importlib
import sys
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_healthz_returns_ok(client):
    response = client.get("/healthz/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_healthz_no_auth_required(client):
    # `client` here is a plain, unauthenticated Django test client.
    response = client.get("/healthz/")

    assert response.status_code == 200
    assert not response.wsgi_request.user.is_authenticated


def test_healthz_reports_db_failure(client):
    with patch("core.views.connection.cursor", side_effect=OperationalError("db is gone")):
        response = client.get("/healthz/")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}


# Mirrors the exact SECURE_SSL_REDIRECT / SECURE_REDIRECT_EXEMPT values set in
# config/settings/prod.py. A container-internal healthcheck reaches gunicorn directly,
# bypassing Caddy, so it never carries X-Forwarded-Proto — without the exemption, SecurityMiddleware
# would 301 it, and `curl -f` treats a 301 as success, reporting "healthy" while never touching
# the database.
@override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^healthz/$"])
def test_healthz_exempt_from_ssl_redirect(client):
    response = client.get("/healthz/", secure=False)

    assert response.status_code == 200


@override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[])
def test_healthz_would_301_without_the_exemption(client):
    """Proves the exemption above is doing real work, not defaulting to a pass either way."""
    response = client.get("/healthz/", secure=False)

    assert response.status_code == 301


def test_healthz_accepts_head(client):
    """Container and load-balancer probes commonly use HEAD, not GET.

    The view is decorated ``@require_safe`` rather than ``@require_GET`` for exactly this
    reason; under ``@require_GET`` a HEAD probe gets 405 and the container reads as unhealthy.
    """
    response = client.head("/healthz/")

    assert response.status_code == 200


def test_healthz_rejects_post(client):
    """A safe-methods-only health check must not accept writes-shaped requests."""
    response = client.post("/healthz/")

    assert response.status_code == 405


def test_healthz_reachable_by_compose_healthcheck_under_real_domain_allowed_hosts(
    client, monkeypatch
):
    """Regression guard for the ALLOWED_HOSTS / healthcheck trap (BLOCKING 5).

    The Compose healthcheck hits gunicorn directly at http://127.0.0.1:8000/healthz/, so the
    probe request carries ``Host: 127.0.0.1`` — a header a deployer's own ALLOWED_HOSTS value
    (a real public domain) would never include on its own. Without config/settings/prod.py's
    ``+ ["127.0.0.1"]``, that probe is rejected with DisallowedHost (400), `app` never reports
    healthy, and caddy's ``depends_on: {app: {condition: service_healthy}}`` means the whole
    stack is never served — a silent, total outage one ALLOWED_HOSTS edit away.

    Imports config.settings.prod fresh, with ALLOWED_HOSTS set to a real domain and nothing
    else, so this fails if the "+ [\"127.0.0.1\"]" in prod.py is ever removed — a value typed
    by hand into @override_settings here, like the SSL-exemption test above, would not depend
    on prod.py at all and so would not catch that regression.
    """
    monkeypatch.setenv("ALLOWED_HOSTS", "plantoplate.example.com")
    sys.modules.pop("config.settings.prod", None)
    try:
        prod_settings = importlib.import_module("config.settings.prod")
        # Sanity check: the input on its own does not already contain 127.0.0.1 — otherwise
        # this test would pass for the wrong reason.
        assert prod_settings.env.list("ALLOWED_HOSTS") == ["plantoplate.example.com"]

        with override_settings(ALLOWED_HOSTS=prod_settings.ALLOWED_HOSTS):
            response = client.get("/healthz/", HTTP_HOST="127.0.0.1")
    finally:
        sys.modules.pop("config.settings.prod", None)

    assert response.status_code == 200
