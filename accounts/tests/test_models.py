import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


def test_user_model_is_custom():
    assert get_user_model().__module__.startswith("accounts")
    assert get_user_model()._meta.label == "accounts.User"


def test_new_user_defaults(user_factory):
    user = user_factory()

    assert user.must_change_password is False
    assert user.temp_password_expires_at is None


def test_password_is_hashed(user_factory):
    plain_password = "correct-horse-battery"
    user = user_factory(password=plain_password)

    assert user.password != plain_password
    assert plain_password not in user.password
    assert user.check_password(plain_password) is True
