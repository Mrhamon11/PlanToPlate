"""``CoreConfig`` also registers the ``OwnedModel`` structural checks (see
``owned_model_errors`` below) with Django's system-checks framework, so that a subclass missing
the owner-XOR-system constraint or a sane default manager fails ``manage.py check`` instead of
merely being wrong at runtime with nothing ever noticing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.apps import AppConfig
from django.core.checks import Error, register

if TYPE_CHECKING:
    from django.apps import AppConfig as AppConfigType
    from django.db.models import Model


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    label = "core"

    def ready(self) -> None:
        register(check_owned_model_subclasses)


def owned_model_errors(model: type[Model]) -> list[Error]:
    """The structural checks a single concrete ``OwnedModel`` subclass must satisfy.

    Both failure modes are *silent* otherwise: Django does not merge an abstract parent's
    ``Meta`` into a child's automatically, so a subclass that declares its own bare
    ``class Meta:`` (which every model wanting ``ordering``, `verbose_name``, or an index will
    want) silently drops the owner-XOR-system ``CheckConstraint`` with no error, no warning, and
    no failing test (03-Ownership-And-Sharing review, blocking finding 4). A subclass that
    overrides ``objects`` with a plain ``models.Manager()`` loses ``visible_to()``/
    ``editable_by()`` the same silent way — the manager is inherited by name, not by guarantee.
    """
    from core.managers import OwnedManager

    errors: list[Error] = []

    if not any(
        constraint.name.endswith("_owner_xor_system") for constraint in model._meta.constraints
    ):
        errors.append(
            Error(
                f"{model.__name__} is a concrete OwnedModel subclass but is missing the "
                "owner-XOR-system CheckConstraint.",
                hint=(
                    "Django does not merge an abstract parent's Meta into a subclass "
                    "automatically. Declare `class Meta(OwnedModel.Meta):` on the subclass "
                    "(adding any extra Meta options there) rather than a bare `class Meta:`."
                ),
                obj=model,
                id="core.E001",
            )
        )

    if not isinstance(model.objects, OwnedManager):
        errors.append(
            Error(
                f"{model.__name__}.objects is not an OwnedManager instance, so "
                "`.visible_to()`/`.editable_by()` are unavailable on its default manager.",
                hint=(
                    "Do not override `objects` on an OwnedModel subclass with a plain "
                    "models.Manager(). If a custom manager is needed, build it from "
                    "OwnedQuerySet (models.Manager.from_queryset(YourQuerySet)) instead."
                ),
                obj=model,
                id="core.E002",
            )
        )

    return errors


def check_owned_model_subclasses(
    app_configs: list[AppConfigType] | None, **kwargs: Any
) -> list[Error]:
    from django.apps import apps as django_apps

    from core.models import OwnedModel

    errors: list[Error] = []
    for model in django_apps.get_models():
        # get_models() never returns abstract models, so any OwnedModel subclass reaching here
        # is concrete by construction.
        if not issubclass(model, OwnedModel):
            continue
        errors.extend(owned_model_errors(model))
    return errors
