import pytest
from django.contrib.auth import get_user_model

from conftest import DEFAULT_TEST_PASSWORD

pytestmark = pytest.mark.django_db


def test_user_factory_creates_user(user_factory):
    user = user_factory()

    assert user.pk is not None
    assert user.check_password(DEFAULT_TEST_PASSWORD)
    assert get_user_model().objects.filter(pk=user.pk).exists()


def test_authenticated_client_is_authenticated(authenticated_client):
    response = authenticated_client.get("/healthz/")

    assert response.wsgi_request.user.is_authenticated
