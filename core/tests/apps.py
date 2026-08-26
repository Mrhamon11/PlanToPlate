"""Registers ``core/tests/models.py`` as its own Django app, ``core_test_fixtures``.

Added to ``INSTALLED_APPS`` only by ``config/settings/test.py`` — see
``Plan/03-Ownership-And-Sharing/tasks.md``, 03.1's note: there is no real domain model yet, so
``OwnedModel`` and the machinery built on top of it are exercised against throwaway concrete
subclasses defined only for this test suite, kept independent of task 04. Because this is a
real ``AppConfig`` rather than a bare module, Django imports ``core.tests.models`` at app-load
time the same way it does for any other installed app, so the dummy models behave exactly like
real ones (migrations, the app registry, ``get_containing_app_config``) instead of relying on
some test file happening to import them first.
"""

from django.apps import AppConfig


class CoreTestFixturesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.tests"
    label = "core_test_fixtures"
    verbose_name = "Core test fixtures"
