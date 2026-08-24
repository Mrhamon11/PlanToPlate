"""Authentication backend that enforces temp-password expiry.

See ``Plan/01-Users-And-Auth/design.md``, "Temp password flow" step 5. ``authenticate()`` has
several entry points — the HTML login view, ``/admin/login/``, and 01.7's API login — and
``ModelBackend.user_can_authenticate`` is the one method every one of those paths already
consults, which makes it the correct choke point for enforcement (as opposed to the message,
which cannot be carried here — see ``accounts.forms.TempPasswordAwareAuthenticationForm``).
Overriding this method also gates ``ModelBackend.get_user()``, so it ends an expired user's
already-open sessions, not just their future logins.
"""

from django.contrib.auth.backends import ModelBackend

from accounts.models import User
from accounts.services import temp_password_expired


class TempPasswordAwareBackend(ModelBackend):
    def user_can_authenticate(self, user: User) -> bool:
        if temp_password_expired(user):
            return False
        return super().user_can_authenticate(user)
