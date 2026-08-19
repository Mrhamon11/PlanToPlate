"""Fixtures shared by every app's test suite.

Written once here so seven apps do not each invent a slightly different user factory.
"""

import factory
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

# Shared with tests/test_conftest.py so the factory's default and the test asserting it stay
# in sync rather than duplicating the literal in two places.
DEFAULT_TEST_PASSWORD = "testpass123"


@pytest.fixture
def api_client() -> APIClient:
    """An unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def user_factory(db):
    """A factory_boy factory that produces persisted users with a usable password."""
    user_model = get_user_model()

    class UserFactory(factory.django.DjangoModelFactory):
        class Meta:
            model = user_model
            django_get_or_create = ("username",)

        username = factory.Sequence(lambda n: f"user{n}")
        email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")

        @classmethod
        def _create(cls, model_class, *args, **kwargs):
            password = kwargs.pop("password", DEFAULT_TEST_PASSWORD)
            user = model_class(*args, **kwargs)
            user.set_password(password)
            user.save()
            return user

    return UserFactory


@pytest.fixture
def authenticated_client(api_client: APIClient, user_factory) -> APIClient:
    """An APIClient logged in as a freshly created user through a real session.

    Uses ``force_login`` rather than DRF's ``force_authenticate`` because this app's real
    auth mechanism is a session cookie (see MILESTONES.md) — a request made through this
    fixture is authenticated the same way AuthenticationMiddleware authenticates any other
    request, DRF view or plain Django view alike.
    """
    user = user_factory()
    api_client.force_login(user)
    return api_client
