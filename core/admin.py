"""Admin registration and shared admin forms for ``core`` (task 09.2, 09.11, 09 rework).

``core`` has one concrete model, ``RecentView`` — private per-user "recently viewed"
telemetry. It is browsable here for operational inspection; everything on it is
machine-written, so the whole row is read-only.

This module also holds the **bulk JSON import** page (09.11): a custom admin view, mounted on
the site by ``config.admin.PlanToPlateAdminSite.get_urls``. Uploading a file runs it through
``core.services.importer.run_import`` — the same function ``manage.py import_json`` calls, so
the two paths cannot drift. The form defaults to a dry run: an admin previews the counts (or
the path-qualified errors) before committing.

``OwnedModelAdminForm`` is the shared fix for the ``owner``-XOR-``is_system`` 500. Every
``OwnedModel`` carries a ``*_owner_xor_system`` ``CheckConstraint`` (``core.models``); the
generic admin form leaves ``owner`` optional and ``is_system`` freely editable, so an admin
who submits the natural "forgot to pick an owner" combination gets an ``IntegrityError`` 500
instead of a form error (04.1-04.5 review finding #10, re-found for the other five models in
the 09.1-09.4 review). This form validates the same rule in ``clean()`` so it surfaces as a
fixable field error. ``modelform_factory`` (which ``ModelAdmin.get_form`` calls) supplies the
concrete ``Meta.model``, so a single base class serves every ``OwnedModel`` ModelAdmin.
"""

from __future__ import annotations

import logging

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse

from core.models import RecentView
from core.schemas import ImportProblem
from core.services.importer import (
    MAX_FILE_BYTES,
    SKIP_EXISTING,
    UPDATE_EXISTING,
    ImportValidationError,
    run_import,
)

logger = logging.getLogger(__name__)


class OwnedModelAdminForm(forms.ModelForm):
    """Rejects the two impossible ``owner`` / ``is_system`` combinations before they reach the
    database ``CheckConstraint``. Attach as ``form = OwnedModelAdminForm`` on any ``OwnedModel``
    ModelAdmin — the concrete model is filled in by ``modelform_factory``.
    """

    def clean(self) -> dict:
        cleaned = super().clean()
        owner = cleaned.get("owner")
        is_system = cleaned.get("is_system")
        if is_system and owner is not None:
            raise ValidationError("A built-in (is_system) object must not have an owner.")
        if not is_system and owner is None:
            raise ValidationError(
                "A non-built-in object must have an owner. Tick 'is system' to make it a "
                "built-in, or pick an owner."
            )
        return cleaned


class ImportJSONForm(forms.Form):
    """The bulk-import upload form (09.11). ``owner`` is a real choice, not a payload value —
    the file can never set it (design.md, "Security notes").
    """

    file = forms.FileField(label="JSON file")
    owner = forms.ModelChoiceField(
        queryset=None,
        help_text="Every imported object is owned by this account.",
    )
    mode = forms.ChoiceField(
        choices=[
            (SKIP_EXISTING, "Skip existing (leave a same-named object untouched)"),
            (UPDATE_EXISTING, "Update existing (overwrite fields and components)"),
        ],
        initial=SKIP_EXISTING,
    )
    dry_run = forms.BooleanField(
        label="Dry run (validate and preview only, write nothing)",
        required=False,
        initial=True,
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = get_user_model().objects.order_by("username")

    def clean_file(self) -> object:
        uploaded = self.cleaned_data["file"]
        if uploaded.size > MAX_FILE_BYTES:
            raise ValidationError(
                f"File is larger than the {MAX_FILE_BYTES // (1024 * 1024)} MB limit."
            )
        return uploaded


def import_json_view(request: HttpRequest, admin_site: admin.AdminSite) -> HttpResponse:
    """Bulk JSON import page. Mounted at ``admin:core_import_json`` by ``PlanToPlateAdminSite``.

    Access is already gated by ``admin_site.admin_view`` (staff, active, no pending forced
    password change).
    """
    report = None
    problems = None
    if request.method == "POST":
        form = ImportJSONForm(request.POST, request.FILES)
        if form.is_valid():
            raw = form.cleaned_data["file"].read()
            try:
                report = run_import(
                    raw=raw,
                    owner=form.cleaned_data["owner"],
                    actor=request.user,
                    mode=form.cleaned_data["mode"],
                    dry_run=form.cleaned_data["dry_run"],
                )
            except ImportValidationError as exc:
                problems = exc.problems
            except Exception:
                # Validation is thorough, but a write it did not anticipate (an IntegrityError
                # or DataError from deep in ``execute``) must still land as a readable problem
                # list, not a 500. The atomic import transaction has already rolled back.
                logger.exception("Bulk JSON import failed during execution")
                problems = [
                    ImportProblem(
                        "",
                        "the import could not be applied — it was rejected by the database. "
                        "Check that every quantity is within range and try again.",
                    )
                ]
    else:
        form = ImportJSONForm(initial={"owner": request.user.pk})

    context = {
        **admin_site.each_context(request),
        "title": "Import JSON",
        "form": form,
        "report": report,
        "problems": problems,
    }
    return TemplateResponse(request, "admin/import_json.html", context)


@admin.register(RecentView)
class RecentViewAdmin(admin.ModelAdmin):
    list_display = ["user", "content_type", "object_id", "viewed_at"]
    list_filter = ["content_type", "viewed_at"]
    search_fields = ["user__username"]
    raw_id_fields = ["user", "content_type"]
    readonly_fields = ["user", "content_type", "object_id", "viewed_at"]
    list_select_related = ["user", "content_type"]

    def has_add_permission(self, request) -> bool:
        return False
