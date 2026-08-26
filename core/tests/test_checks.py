"""Tests for the ``OwnedModel`` structural checks registered in ``core/apps.py`` (03-Ownership-
And-Sharing review, blocking finding 4).

Django does not merge an abstract parent's ``Meta`` into a child's automatically, so a subclass
that declares its own bare ``class Meta:`` silently drops the owner-XOR-system
``CheckConstraint`` — no error, no warning, no failing test, until something inspects ``_meta``
after the app registry has finished loading. That "something" is Django's own system-checks
framework; these tests exercise the check function it calls directly, plus confirm it is
actually wired up rather than merely importable.
"""

from __future__ import annotations

from django.core.checks.registry import registry
from django.db import models

from core.apps import check_owned_model_subclasses, owned_model_errors
from core.tests.models import DummyNode, DummyOwned


def test_wellformed_owned_models_pass_cleanly():
    assert owned_model_errors(DummyOwned) == []
    assert owned_model_errors(DummyNode) == []


def test_missing_owner_xor_system_constraint_is_reported(monkeypatch):
    monkeypatch.setattr(DummyOwned._meta, "constraints", [])

    errors = owned_model_errors(DummyOwned)

    assert any(e.id == "core.E001" for e in errors)


def test_non_owned_manager_is_reported(monkeypatch):
    monkeypatch.setattr(DummyOwned, "objects", models.Manager())

    errors = owned_model_errors(DummyOwned)

    assert any(e.id == "core.E002" for e in errors)


def test_check_is_registered_with_django_and_currently_clean():
    """Confirms the check actually runs as part of ``manage.py check`` (not just importable),
    and that today's fixture models pass it — a regression guard against the check itself
    silently stopping being wired up.

    Asserting only that ``run_checks()`` reports no ``core.E0*`` errors does not discriminate:
    an unregistered check also contributes zero results, so that assertion alone stays green
    even if ``CoreConfig.ready()`` never calls ``register(check_owned_model_subclasses)``
    (03-Ownership-And-Sharing review, iteration-2 blocking finding 7). Asserting the function's
    actual presence in the registry closes that gap.
    """
    assert check_owned_model_subclasses in registry.registered_checks

    errors = registry.run_checks()

    assert not [e for e in errors if e.id and e.id.startswith("core.E0")]
