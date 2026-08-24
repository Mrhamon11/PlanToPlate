"""HTML views for authentication and the temp-password flow.

See ``Plan/01-Users-And-Auth/design.md``, "Views and endpoints", for the route table this
implements, and "Temp password flow" step 4 for why
``TempPasswordAwarePasswordChangeForm.save`` routes through ``accounts.services
.complete_password_change`` instead of the default ``SetPasswordMixin.set_password_and_save``.
"""

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from accounts.forms import TempPasswordAwareAuthenticationForm
from accounts.services import complete_password_change


class TempPasswordAwareLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = TempPasswordAwareAuthenticationForm


class TempPasswordAwarePasswordChangeForm(PasswordChangeForm):
    """Persists through ``complete_password_change`` rather than the default save path.

    The inherited ``SetPasswordMixin.save()`` only calls ``set_password()``/``save()`` — it
    never clears ``must_change_password``/``temp_password_expires_at``, which would strand a
    forced-reset user in the redirect loop after "successfully" changing their password.

    ``PasswordChangeView.form_valid`` calls ``form.save()`` then
    ``update_session_auth_hash(request, form.user)`` — exactly the ordering design.md step 4
    requires, satisfied here by subclassing rather than reimplementing ``form_valid``.
    """

    def save(self, commit=True):
        complete_password_change(self.user, self.cleaned_data["new_password1"])
        return self.user


class ForcedAwarePasswordChangeView(PasswordChangeView):
    form_class = TempPasswordAwarePasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["forced"] = self.request.user.must_change_password
        return context


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"
