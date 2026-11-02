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
from accounts.throttling import (
    PASSWORD_CHANGE_THROTTLE_RATE,
    PASSWORD_CHANGE_THROTTLE_SCOPE,
    check_login_throttle,
    reset_login_throttle,
)
from core.services.ratelimit import check_rate_limit


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
        # Captured before super().post() runs the form: request.user.is_authenticated
        # afterward reflects whatever session was already attached to the request, not whether
        # *this* POST's credentials were valid. Resetting on that post-hoc, cause-agnostic check
        # let anyone already holding any authenticated session submit wrong credentials for a
        # different target account in a loop with zero throttling — every attempt recorded into
        # the shared bucket was wiped again immediately after, because the caller was (and
        # remained) logged in as themselves throughout (task 10 review, blocking finding). Only
        # a login that flips this request's own session from anonymous to authenticated counts
        # as this request having performed the successful authentication.
        was_authenticated_before = request.user.is_authenticated
        response = super().post(request, *args, **kwargs)
        if not was_authenticated_before and request.user.is_authenticated:
            # 10.5 carried finding: a successful login must not keep spending the shared IP
            # budget — see accounts.throttling.reset_login_throttle.
            reset_login_throttle(request)
        return response


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
    # Same fix and same reasoning as ThrottledLoginMixin.post above: captured before
    # admin.site.login() runs, so the reset below only fires when *this* POST is what
    # authenticated the session, never merely because the caller was already logged in as
    # someone else when they submitted a wrong password for a different target account.
    was_authenticated_before = request.user.is_authenticated
    response = admin.site.login(request, *args, **kwargs)
    if request.method == "POST" and not was_authenticated_before and request.user.is_authenticated:
        # django.contrib.auth.login() (called inside admin.site.login() on success) sets
        # request.user directly, so this is reachable right after the call returns — see
        # accounts.throttling.reset_login_throttle.
        reset_login_throttle(request)
    return response


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

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """10.5: password change is throttled the same as login (5/min), sharing one bucket
        with ``accounts.api.PasswordChangeAPIView`` (see ``accounts.throttling``'s constants).
        Keyed on the requester's own primary key — unlike login, the caller here already holds
        a real session, so there is no "which account is attacking which" ambiguity to worry
        about.
        """
        throttled = check_rate_limit(
            request,
            scope=PASSWORD_CHANGE_THROTTLE_SCOPE,
            rate=PASSWORD_CHANGE_THROTTLE_RATE,
        )
        if throttled is not None:
            return throttled
        return super().post(request, *args, **kwargs)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"
