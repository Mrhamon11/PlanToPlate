"""Auth forms.

See ``Plan/01-Users-And-Auth/design.md``, "Temp password flow" step 5, "Enforcement and the
message are separate layers, and the backend cannot carry both" — for why the expiry message
has to be reconstructed here rather than raised from ``TempPasswordAwareBackend``.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from accounts.services import temp_password_expired


class TempPasswordAwareAuthenticationForm(AuthenticationForm):
    """``AuthenticationForm`` that reports temp-password expiry with its own message.

    ``TempPasswordAwareBackend.user_can_authenticate`` is the actual enforcement point — it
    makes ``authenticate()`` return ``None`` for a user whose temp password has expired. But a
    ``None`` result gives ``AuthenticationForm.clean`` no user to reason about, so it falls
    back to the generic "please enter a correct username and password" message, and
    ``confirm_login_allowed`` never runs (it only fires once ``authenticate()`` has returned a
    user). So the expiry-specific copy is reconstructed here: after the generic failure, the
    raw submitted credentials are re-checked directly against the same condition the backend
    used. This is not a new user-enumeration oracle — it only distinguishes "expired" from
    "wrong password" for someone who has already supplied the *correct* password.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "temp_password_expired": _(
            "This temporary password has expired. Ask an admin to issue a new one."
        ),
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            username = self.cleaned_data.get("username")
            password = self.cleaned_data.get("password")
            if username and password:
                user_model = get_user_model()
                try:
                    user = user_model._default_manager.get_by_natural_key(username)
                except user_model.DoesNotExist:
                    # Run the hasher anyway, exactly as ModelBackend.authenticate does on the
                    # same DoesNotExist branch (Django #20760) — otherwise this reconstruction
                    # does an extra check_password() only when the username exists, undoing that
                    # deliberate timing equalisation and turning it back into a remotely
                    # separable, unauthenticated user-enumeration oracle.
                    user_model().set_password(password)
                    user = None
                if (
                    user is not None
                    and user.check_password(password)
                    and temp_password_expired(user)
                ):
                    raise forms.ValidationError(
                        self.error_messages["temp_password_expired"],
                        code="temp_password_expired",
                    ) from None
            raise
