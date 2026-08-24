"""HTML views for authentication and the temp-password flow.

See ``Plan/01-Users-And-Auth/design.md``, "Views and endpoints", for the route table this
implements, and "Temp password flow" step 4 for why
``TempPasswordAwarePasswordChangeForm.save`` routes through ``accounts.services
.complete_password_change`` instead of the default ``SetPasswordMixin.set_password_and_save``.
"""

from django.contrib import admin
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.http import HttpRequest, HttpResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from accounts.forms import TempPasswordAwareAuthenticationForm
from accounts.services import complete_password_change
from accounts.throttling import check_login_throttle


class ThrottledLoginMixin:
    """Applies the shared login throttle (scope ``login``, see ``accounts.throttling``) to a
    plain Django view.

    Keyed on the requester's IP (an anonymous login POST has no authenticated user to key on
    instead), per design.md's "Login throttling": the limit must slow an attacker down without
    ever giving them a way to lock out the real account, since accounts here are
    admin-provisioned with no self-service recovery.

    Shares its cache key/scope with ``accounts.api.LoginAPIView`` and ``throttled_admin_login``
    below — the same IP is rate-limited across all three login endpoints combined, not
    budgeted separately per endpoint. That scope lives in ``accounts.throttling`` and is
    deliberately not overridable per view: a ``throttle_scope`` attribute here would read like
    the knob that sets it while changing nothing (``check_login_throttle`` passes its own
    target), and a working knob would be a way to break the shared bucket by accident.
    """

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        throttled = check_login_throttle(request)
        if throttled is not None:
            return throttled
        return super().post(request, *args, **kwargs)


def throttled_admin_login(request: HttpRequest, *args, **kwargs) -> HttpResponse:
    """Wraps Django Admin's own login view with the same throttle as the other two login paths.

    ``/admin/login/`` calls ``authenticate()`` exactly like the HTML and API logins but is
    Django's own ``AdminSite.login`` rather than a view this project defines, so it shares
    neither's throttle mixin/class on its own. Found unthrottled entirely in iteration 1's
    security review — the account it fronts is the worst one: ``bootstrap_admin`` creates a
    superuser at the guessable default username ``admin``.

    Mounted in ``config/urls.py`` at ``admin/login/``, ahead of ``admin.site.urls`` — Django's
    resolver tries patterns in order, so this intercepts the request before the admin's own
    ``login/`` pattern would. ``reverse("admin:login")`` is unaffected, since name resolution
    still points at the pattern inside ``admin.site.urls``; both happen to produce the same
    path, which is exactly why this interception works.
    """
    if request.method == "POST":
        throttled = check_login_throttle(request)
        if throttled is not None:
            return throttled
    return admin.site.login(request, *args, **kwargs)


class TempPasswordAwareLoginView(ThrottledLoginMixin, LoginView):
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
