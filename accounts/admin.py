"""Admin surface for the custom ``User`` model (task 09.2, 09.5–09.8).

Beyond table browsing, this adds the four purpose-built account flows from
``Plan/09-Admin-Control-Center/design.md`` ("User management"):

- **Create user** — a custom page that generates a one-time temp password and shows it
  exactly once (``accounts_user_create``); the stock add form is redirected here.
- **Reset password** — a bulk action that issues a fresh temp password, forces a change, and
  ends every session the account holds.
- **Delete user** — a confirmation page showing per-model CASCADE counts and requiring the
  username to be typed. The D41 two-FK tombstone blind spot and the D53 PROTECT-clearing
  pre-pass (self-owned components deleted outright, cross-owner ones neutralized) are both
  reconciled before the cascade, so neither blocks this whole-account delete.
- **Entitlement** — grant / revoke ``is_staff``, guarded so the last active admin cannot lose
  access by demotion *or* deletion.

All business logic (temp passwords, the last-admin guard, session invalidation, the D41 / D53
pre-passes) lives in ``accounts.services`` and the services it calls; this module is the thin
admin adapter.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.utils import get_deleted_objects
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from accounts import services
from accounts.models import User
from core.services import audit


class UserCreationAdminForm(forms.ModelForm):
    """The create-user page's form — identity fields only. The password is generated, never
    entered (design.md, "Create user").
    """

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_staff"]


class GuardedUserChangeForm(UserChangeForm):
    """Stock change form minus the password hash display (design.md, "Security notes": an admin
    can never see an existing password — not even its hash), plus the last-admin guard: the
    only active admin cannot clear their own ``is_staff`` / ``is_active`` through the form.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields.pop("password", None)

    def clean(self) -> dict:
        cleaned = super().clean()
        instance = self.instance
        if instance.pk and instance.is_staff and instance.is_active:
            losing_staff = not cleaned.get("is_staff", instance.is_staff)
            losing_active = not cleaned.get("is_active", instance.is_active)
            if (losing_staff or losing_active) and services.is_last_admin(instance):
                raise ValidationError(
                    f"{instance.username} is the only active admin — grant another account "
                    "admin access before removing this one's."
                )
        return cleaned


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = GuardedUserChangeForm
    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "must_change_password",
    ]
    list_filter = ["is_staff", "is_superuser", "is_active", "must_change_password"]
    search_fields = ["username", "email", "first_name", "last_name"]
    readonly_fields = ["last_login", "date_joined", "temp_password_expires_at"]
    actions = ["reset_temp_password", "grant_admin", "revoke_admin"]
    fieldsets = (
        (None, {"fields": ("username",)}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        (
            "Temp password flow",
            {"fields": ("must_change_password", "temp_password_expires_at")},
        ),
    )

    # -- custom URLs --------------------------------------------------------------------

    def get_urls(self) -> list:
        custom = [
            path(
                "create/",
                self.admin_site.admin_view(self.create_user_view),
                name="accounts_user_create",
            ),
        ]
        # ``DjangoUserAdmin`` registers ``<id>/password/`` (``auth_user_password_change``),
        # a form that sets an *arbitrary, known* password with no token revocation, no session
        # kill, and no audit record — it bypasses the 09.6 reset invariant that every
        # password-setting path routes through a service (design.md, "Security notes";
        # ``tasks.md`` 09.6). Replace it with a redirect to the reset-password action so a
        # stale link or a hand-typed URL cannot reach it, and so the URL name still reverses.
        base = []
        for pattern in super().get_urls():
            if getattr(pattern, "name", None) == "auth_user_password_change":
                base.append(
                    path(
                        "<id>/password/",
                        self.admin_site.admin_view(self.disabled_password_change_view),
                        name="auth_user_password_change",
                    )
                )
            else:
                base.append(pattern)
        return custom + base

    def disabled_password_change_view(
        self, request: HttpRequest, id: str, *args: object, **kwargs: object
    ) -> HttpResponse:
        """The stock set-a-known-password form is disabled (see ``get_urls``). Point the admin
        at the sanctioned mechanism — the ``Reset password`` action, which issues a one-time
        temp password, ends every session, and writes the audit record.
        """
        self.message_user(
            request,
            "Setting a chosen password is disabled. Select the account on the user list and "
            "run the 'Reset password' action to issue a one-time temporary password.",
            messages.WARNING,
        )
        return redirect("admin:accounts_user_changelist")

    def add_view(
        self, request: HttpRequest, form_url: str = "", extra_context: dict | None = None
    ) -> HttpResponse:
        """The stock "Add user" button lands on the purpose-built create page instead."""
        return redirect("admin:accounts_user_create")

    def _admin_context(self, request: HttpRequest, **extra: object) -> dict:
        return {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "app_label": self.opts.app_label,
            **extra,
        }

    # -- 09.5 create user -------------------------------------------------------------

    def create_user_view(self, request: HttpRequest) -> HttpResponse:
        if not self.has_add_permission(request):
            raise PermissionDenied
        temp_password = None
        created_user = None
        if request.method == "POST":
            form = UserCreationAdminForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                created_user, temp_password = services.create_user(
                    actor=request.user,
                    username=data["username"],
                    email=data["email"],
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    is_staff=data["is_staff"],
                )
                self.log_addition(
                    request,
                    created_user,
                    [{"added": {"name": "user", "object": str(created_user)}}],
                )
                self.message_user(
                    request,
                    f"Created user {created_user.username}. The temp password is shown below "
                    "once and will not be shown again.",
                    messages.SUCCESS,
                )
        else:
            form = UserCreationAdminForm()
        context = self._admin_context(
            request,
            title="Create user",
            form=form,
            temp_password=temp_password,
            created_user=created_user,
            changelist_url=reverse("admin:accounts_user_changelist"),
        )
        return TemplateResponse(request, "admin/create_user.html", context)

    # -- 09.6 reset password --------------------------------------------------------

    @admin.action(description="Reset password (new temp password, end all sessions)")
    def reset_temp_password(self, request: HttpRequest, queryset) -> HttpResponse:
        results = [
            (user, services.reset_password(actor=request.user, user=user)) for user in queryset
        ]
        context = self._admin_context(
            request,
            title="Temporary passwords issued",
            results=results,
            changelist_url=reverse("admin:accounts_user_changelist"),
        )
        return TemplateResponse(request, "admin/reset_password_done.html", context)

    # -- 09.8 entitlement ----------------------------------------------------------------

    @admin.action(description="Grant admin access (is_staff)")
    def grant_admin(self, request: HttpRequest, queryset) -> None:
        changed = sum(
            services.set_entitlement(actor=request.user, user=user, is_staff=True)
            for user in queryset
        )
        self.message_user(
            request, f"Granted admin access to {changed} account(s).", messages.SUCCESS
        )

    @admin.action(description="Revoke admin access (is_staff)")
    def revoke_admin(self, request: HttpRequest, queryset) -> None:
        try:
            with transaction.atomic():
                changed = sum(
                    services.set_entitlement(actor=request.user, user=user, is_staff=False)
                    for user in queryset
                )
        except services.LastAdminError as exc:
            # All-or-nothing: without the wrapping transaction, a demotion that hit the
            # last-admin guard part-way through would leave the accounts already processed
            # demoted and committed before the action aborted.
            self.message_user(request, str(exc), messages.ERROR)
            return
        self.message_user(
            request, f"Revoked admin access from {changed} account(s).", messages.SUCCESS
        )

    def save_model(self, request: HttpRequest, obj: User, form, change: bool) -> None:
        """Audit an ``is_staff`` toggle made through the generic change form.

        This does *not* route through ``services.set_entitlement``: by the time ``save_model``
        runs, the form has already written the new ``is_staff`` onto ``obj``, so
        ``set_entitlement`` (which compares the requested value against the current one and
        no-ops when they match) would record nothing. The last-admin guard for this path lives
        in ``GuardedUserChangeForm.clean`` instead; here we only emit the same audit record
        the service would have, through the same helper.
        """
        entitlement_now = obj.is_staff if change and "is_staff" in form.changed_data else None
        super().save_model(request, obj, form, change)
        if entitlement_now is not None:
            audit.record_entitlement_change(actor=request.user, target=obj, granted=entitlement_now)

    # -- 09.7 delete user with preview -----------------------------------------------

    def delete_view(
        self, request: HttpRequest, object_id: str, extra_context: dict | None = None
    ) -> HttpResponse:
        user = self.get_object(request, object_id)
        if user is None or not self.has_delete_permission(request, user):
            raise PermissionDenied
        # The trailing element is Django's own ``protected`` list from a bare collector run on
        # ``[user]``. It is not used: ``DishComponent.recipe`` and ``RecipeComponent.ingredient``
        # / ``sub_recipe`` are the only ``PROTECT`` relations that can appear in a user's
        # cascade, and ``services.delete_user``'s D53 pre-pass clears both shapes (self-owned
        # rows deleted outright, cross-owner rows neutralized) before the real delete runs — so
        # a whole-account delete no longer refuses on them, and this preview must not warn
        # about a block that will not actually happen (``ARCHITECTURE.md`` D53).
        _, model_count, _, _ = get_deleted_objects([user], request, self.admin_site)

        if request.method == "POST":
            if services.is_last_admin(user):
                self.message_user(
                    request,
                    f"{user.username} is the only active admin — deleting it locks everyone "
                    "out. Grant another account admin access first.",
                    messages.ERROR,
                )
                return redirect(request.path)
            if request.POST.get("confirmation", "") != user.get_username():
                self.message_user(
                    request,
                    "The confirmation text did not match the username — nothing was deleted.",
                    messages.WARNING,
                )
                return redirect(request.path)
            obj_repr = str(user)
            deleted_pk = user.pk
            try:
                services.delete_user(actor=request.user, user=user)
            except services.LastAdminError as exc:
                # The ``is_last_admin`` check above already covers the ordinary case; this
                # only fires on a concurrent-demotion race, where the service's own guard
                # trips. Surface it as a message like the other refusals — and never write
                # the deletion ``LogEntry`` until the delete has actually happened.
                self.message_user(request, str(exc), messages.ERROR)
                return redirect(request.path)
            # ``user.delete()`` nulls ``user.pk`` via the collector; restore it so the audit
            # record carries the real id.
            user.pk = deleted_pk
            self.log_deletion(request, user, obj_repr)
            self.message_user(request, f"Deleted user {obj_repr}.", messages.SUCCESS)
            return redirect("admin:accounts_user_changelist")

        context = self._admin_context(
            request,
            title="Delete user",
            object=user,
            model_counts=sorted(model_count.items()),
            changelist_url=reverse("admin:accounts_user_changelist"),
        )
        return TemplateResponse(request, "admin/delete_user_confirm.html", context)

    def get_actions(self, request: HttpRequest) -> dict:
        """Drop the stock bulk "delete selected" action. Deleting a user is a destructive
        cascade that design.md requires be gated behind a per-model preview *and* the username
        typed to confirm; ``delete_selected`` only shows the generic confirm page and skips
        that step. The guarded single-user ``delete_view`` is the only deletion route.
        """
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_model(self, request: HttpRequest, obj: User) -> None:
        """Route ``ModelAdmin``'s single-object delete hook through the service so the D41
        tombstone pre-pass runs and the last active admin is protected, whatever calls it.
        """
        services.delete_user(actor=request.user, user=obj)
