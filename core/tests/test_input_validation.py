"""Input-validation sweep (10.2 — ``Plan/10-Security-And-Deployment/test-plan.md``).

Every endpoint accepting user input needs field-level validators, length caps on text fields
(an unbounded ``TextField`` is a cheap denial-of-service), ``Decimal`` bounds on quantities, and
no unvalidated ``JSONField`` writes. The first two are swept generically across every model in
the project's own apps — the same "walk the real registry, prove the walk is not vacuous"
pattern ``core/tests/test_conventions.py`` established for the visibility keystone.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.tests.test_project_structure import EXPECTED_APP_LABELS
from planner.models import MealPlanProfile

pytestmark = pytest.mark.django_db

#: JSONFields that are never populated from raw user input — server-computed and read-only on
#: every write path — so "no unvalidated JSONField writes" does not apply to them. See
#: ARCHITECTURE.md D48 and planner/serializers.py's module docstring:
#: ``MealPlan.profile_snapshot`` is a ``SerializerMethodField`` on read and is never deserialised
#: from a request at all; ``planner.services.persist.build_profile_snapshot`` is its only writer.
_JSON_FIELDS_EXEMPT_FROM_VALIDATION = {("planner", "mealplan", "profile_snapshot")}


def _project_models() -> list[type[models.Model]]:
    return [m for m in django_apps.get_models() if m._meta.app_label in EXPECTED_APP_LABELS]


# --- text fields: every TextField must have a cap -----------------------------------------


def _text_fields_missing_max_length(fields: list[tuple[str, models.Field]]) -> list[str]:
    return [
        name
        for name, field in fields
        if isinstance(field, models.TextField) and field.max_length is None
    ]


def test_text_field_max_length_check_detects_an_unbounded_field():
    """Proves the detection helper below is not vacuous before trusting it against real
    models: an unbounded field must be flagged, a bounded one must not.
    """
    fields = [
        ("body", models.TextField()),
        ("bounded", models.TextField(max_length=500)),
    ]

    assert _text_fields_missing_max_length(fields) == ["body"]


def test_all_text_fields_have_max_length():
    """An unbounded ``TextField`` on a user-writable model is a cheap denial-of-service —
    nothing stops one write from being gigabytes. Every concrete model in the project's own
    apps (not Django's own contrib apps, not the throwaway ``core.tests`` fixtures) must cap
    every ``TextField`` it declares, including ones inherited from ``OwnedModel``.
    """
    offenders = []
    for model in _project_models():
        fields = [(f.name, f) for f in model._meta.get_fields() if isinstance(f, models.Field)]
        missing = _text_fields_missing_max_length(fields)
        if missing:
            offenders.append(f"{model._meta.app_label}.{model.__name__}: {missing}")

    assert offenders == [], f"unbounded TextField(s) found (cheap DoS): {offenders}"


# --- decimal fields: every DecimalField must reject an out-of-range value -----------------


def _decimal_field_has_lower_bound(field: models.DecimalField) -> bool:
    """True if ``field`` rejects an obviously-invalid negative value through its own
    validators.

    Every ``DecimalField`` always carries Django's built-in digit-count validator (from
    ``max_digits``/``decimal_places``), so checking ``field.validators`` for "any validator at
    all" would pass vacuously for a field with no author-supplied bound. Actually running the
    validators against ``-1`` is what proves a *business* bound (never negative — the shared
    domain rule for every quantity/factor/servings/bias field in this project) is wired in,
    not merely inferred from the field's ``max_digits``.
    """
    try:
        field.run_validators(Decimal("-1"))
    except DjangoValidationError:
        return True
    return False


def test_decimal_field_bound_check_detects_a_missing_validator():
    unbounded = models.DecimalField(max_digits=5, decimal_places=2)
    bounded = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )

    assert _decimal_field_has_lower_bound(unbounded) is False
    assert _decimal_field_has_lower_bound(bounded) is True


def test_decimal_fields_have_bounds():
    """Every ``DecimalField`` in the project's own apps is a quantity, a conversion factor, a
    scale, or a weighting — none of them are meaningfully negative — so each one must carry a
    validator that actually rejects a negative value, not just an implicit ``max_digits`` cap.
    """
    offenders = []
    for model in _project_models():
        for field in model._meta.get_fields():
            if not isinstance(field, models.DecimalField):
                continue
            if not _decimal_field_has_lower_bound(field):
                offenders.append(f"{model._meta.app_label}.{model.__name__}.{field.name}")

    assert offenders == [], f"DecimalField(s) with no lower bound: {offenders}"


# --- JSON fields: every user-writable JSONField must validate its structure ---------------


def test_json_fields_validated():
    """Every ``JSONField`` in the project's own apps either validates its structure or is a
    documented exemption (server-computed, never deserialised from a request) — an
    unvalidated ``JSONField`` write accepts literally any JSON, including something that later
    crashes a reader expecting a particular shape.
    """
    offenders = []
    for model in _project_models():
        for field in model._meta.get_fields():
            if not isinstance(field, models.JSONField):
                continue
            key = (model._meta.app_label, model._meta.model_name, field.name)
            if key in _JSON_FIELDS_EXEMPT_FROM_VALIDATION:
                continue
            if not field.validators:
                offenders.append(f"{model._meta.app_label}.{model.__name__}.{field.name}")

    assert offenders == [], f"unvalidated JSONField(s): {offenders}"


def test_profile_tag_limits_rejects_an_arbitrary_structure():
    """The concrete case the sweep above proves generically: ``MealPlanProfile.tag_limits``
    must reject something that is not "a mapping of tag name to a non-negative whole number" —
    a bare list, a nested structure, a negative or non-integer limit.
    """
    field = MealPlanProfile._meta.get_field("tag_limits")

    for bad_value in (
        ["chicken", "beef"],
        {"chicken": -1},
        {"chicken": "a lot"},
        {"chicken": 1.5},
        {1: 2},
    ):
        with pytest.raises(DjangoValidationError):
            field.run_validators(bad_value)


def test_profile_slots_rejects_an_arbitrary_structure():
    """The second concrete case: ``MealPlanProfile.slots`` must reject an empty list and an
    unknown slot name, not just anything that happens to be a list.

    Uses ``field.clean()`` rather than ``run_validators()`` here: an empty list and ``None``
    are both in Django's ``Field.empty_values`` and so never reach ``validate_slots`` through
    ``run_validators`` at all — they are rejected one step earlier, by ``Field.validate()``'s
    own blank/null checks (``slots`` is neither ``blank=True`` nor ``null=True``). ``clean()``
    runs both steps, matching what actually happens on a real save.
    """
    field = MealPlanProfile._meta.get_field("slots")

    for bad_value in ([], ["BRUNCH"], "DINNER", None):
        with pytest.raises(DjangoValidationError):
            field.clean(bad_value, None)


# --- oversized payloads: Django's own DATA_UPLOAD_MAX_MEMORY_SIZE default -----------------


def _post_oversized_name(client):
    return client.post(
        "/api/ingredients/",
        {"name": "x" * (3 * 1024 * 1024)},
        format="json",
    )


def test_oversized_payload_rejected(authenticated_client):
    """Django's ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (2.5 MB default, never overridden upward
    anywhere in ``config/settings``) is a project-wide cap on every request body — this proves
    it is actually in effect against a real endpoint, not merely un-overridden in theory.

    The field's own ``max_length`` also rejects a 3 MB name, so a bare ``== 400`` cannot tell
    the two apart. The size cap fires while the body is being read, before any field
    validation, and answers with Django's plain-HTML 400 rather than a DRF JSON error body.
    """
    response = _post_oversized_name(authenticated_client)

    assert response.status_code == 400
    assert "application/json" not in response["Content-Type"]
    assert b"Bad Request" in response.content


def test_oversized_payload_control_reaches_field_validation_without_the_cap(
    authenticated_client, settings
):
    """The control that makes the test above mean something: with the cap lifted the same
    payload gets as far as field validation and fails there with a JSON error instead."""
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = None

    response = _post_oversized_name(authenticated_client)

    assert response.status_code == 400
    assert "application/json" in response["Content-Type"]
    assert "name" in response.json()
