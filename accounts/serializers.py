"""Serializers for ``/api/auth/`` — see ``Plan/01-Users-And-Auth/design.md``.

Business logic stays in ``accounts.services`` per ``CLAUDE.md`` §3; these serializers validate
input at the API boundary and delegate the actual writes.
"""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.services import complete_password_change, temp_password_expired

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """The current user, safe to return verbatim — no password field exists on it."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "must_change_password",
            "date_joined",
            "is_staff",
        ]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    """Validates credentials via ``authenticate()`` rather than a direct password check, so
    every enforcement layer that hangs off ``authenticate()`` — including
    ``TempPasswordAwareBackend``'s expiry check — applies here too.
    """

    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        request = self.context["request"]
        user = authenticate(request, username=attrs["username"], password=attrs["password"])
        if user is None:
            # One message for both a wrong password and a nonexistent username — a different
            # message per case is a user-enumeration oracle (design.md, "Edge cases").
            raise serializers.ValidationError(
                "Unable to log in with the provided credentials.",
                code="authorization",
            )
        attrs["user"] = user
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)
    new_password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)

    def validate_old_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Your old password was entered incorrectly.")
        # An expired temp password must not be a valid ``old_password`` here, or the API path
        # becomes a self-service way to clear must_change_password/temp_password_expires_at with
        # no admin involvement — exactly the door design.md step 5 says must stay closed. The
        # HTML and session paths are already closed by TempPasswordAwareBackend; this endpoint
        # never calls authenticate(), so it needs its own check.
        if temp_password_expired(user):
            raise serializers.ValidationError(
                "This temporary password has expired. Ask an admin to issue a new one."
            )
        return value

    def validate_new_password(self, value: str) -> str:
        # complete_password_change validates again internally — this is what turns a bad
        # password into a field-level 400 instead of a service-layer ValidationError the view
        # would have to translate by hand.
        validate_password(value, user=self.context["request"].user)
        return value

    def save(self) -> User:
        user = self.context["request"].user
        complete_password_change(user, self.validated_data["new_password"])
        return user
