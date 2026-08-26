"""View mixins shared by every screen (design.md, "Base view helpers").

``HtmxTemplateMixin`` and ``MessageMixin`` are the two pieces every HTMX-backed view needs.
``OwnedObjectMixin`` (03.9) is the HTML-side counterpart of ``core.viewsets.OwnedViewSetMixin``
— see its own docstring below for what it does.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db.models import QuerySet
from django.forms import BaseModelForm
from django.http import HttpRequest
from django.template.loader import render_to_string

from core.permissions import IsOwnerOrReadOnly

# The HTML-side counterpart of core/serializers.py's OwnedSerializer read-only fields (see that
# module's docstring). A ModelForm that exposes any of these gives its owner a write path
# straight to sharing/provenance state that skips core/services/sharing.py's cascade-refusal
# check entirely -- the same hole a writable `visibility` on OwnedSerializer would open.
UNSAFE_OWNED_MODEL_FORM_FIELDS = frozenset(
    {"owner", "is_system", "shared_with", "copied_from", "visibility"}
)


class HtmxTemplateMixin:
    """Renders ``partial_template_name`` for an HTMX request, ``template_name`` otherwise.

    ``request.htmx`` is set by ``core.middleware.HtmxMiddleware`` from the ``HX-Request``
    header. A view that never sets ``partial_template_name`` behaves exactly like a plain
    ``TemplateResponseMixin`` subclass — the HTMX branch only engages once a fragment
    template is actually declared, so adding this mixin to a class is never itself a
    behaviour change.

    An ``hx-boost`` navigation also sends ``HX-Request``, but its swap target is
    ``document.body`` via ``innerHTML`` — it wants the whole page, not a fragment. The mixin
    therefore only serves the partial for a targeted ``hx-get``/``hx-post``/etc., never for a
    boosted request (``request.htmx_boosted``, also set by ``HtmxMiddleware``).
    """

    template_name: str
    partial_template_name: str | None = None
    request: HttpRequest

    def get_template_names(self) -> list[str]:
        if (
            getattr(self.request, "htmx", False)
            and not getattr(self.request, "htmx_boosted", False)
            and self.partial_template_name
        ):
            return [self.partial_template_name]
        return super().get_template_names()


class MessageMixin:
    """Adds a Django ``messages`` flash message, and — for an HTMX fragment response — appends
    the rendered ``_partials/_messages.html`` OOB swap so the message reaches ``#messages``
    even though the fragment itself never touches that element (design.md, "HTMX
    conventions": "any fragment response can raise a message without owning the page").

    A full-page (non-HTMX) response needs no special handling here: ``base.html`` already
    includes ``_messages.html`` in the normal render, and Django's messages framework carries
    the message across the request via its storage backend exactly as it always does.
    """

    request: HttpRequest

    def add_message(self, level: int, message_text: str) -> None:
        messages.add_message(self.request, level, message_text)

    def render_to_response(self, context: dict[str, Any], **response_kwargs: Any):
        response = super().render_to_response(context, **response_kwargs)
        if getattr(self.request, "htmx", False):
            # TemplateResponse is lazy — .render() must run before .content can be appended
            # to, and before any middleware further up the stack (e.g. HtmxMiddleware) reads
            # response.content or status.
            response.render()
            oob = render_to_string("_partials/_messages.html", request=self.request)
            response.content += oob.encode(response.charset or "utf-8")
        return response


class OwnedObjectMixin:
    """The HTML-view counterpart of ``OwnedViewSetMixin`` (core/viewsets.py) — the same two-
    layer defence design.md's "Permissions" section requires, applied to Django's generic
    class-based views (``ListView``, ``DetailView``, ``UpdateView``, ``DeleteView``) instead of
    a DRF viewset, so template-rendered screens have no second, weaker path to owned data
    (MILESTONES.md section 6).

    Mix in ahead of the Django generic view class, e.g.::

        class RecipeDetailView(OwnedObjectMixin, DetailView):
            model = Recipe

    ``get_queryset()`` is the primary defence: every ``ListView``/``DetailView``/``UpdateView``/
    ``DeleteView`` built on this mixin only ever sees ``.visible_to(request.user)`` — an object
    outside that set never reaches the view at all, and ``get_object()`` 404s on it exactly like
    a missing row would, which is what keeps a private object's non-existence indistinguishable
    from someone else's private object (design.md, "Enumeration").

    ``get_object()`` adds the secondary defence: reusing ``IsOwnerOrReadOnly`` directly, the
    exact permission class ``OwnedViewSetMixin`` uses for the API's plain CRUD verbs, rather
    than re-deriving the same "owner-only for unsafe methods" rule a second time (MILESTONES.md
    section 6: "never implement the same rule twice"). ``IsOwnerOrReadOnly`` only ever reads
    ``request.method`` and ``request.user``, both of which a plain Django ``HttpRequest`` has,
    so it works unmodified against ``self.request`` here — no DRF request wrapper needed. A
    GET against an object merely shared with (not owned by) the requester still succeeds, since
    GET is a safe method; a POST (the only verb an HTML ``<form>`` sends — this also covers an
    htmx ``hx-put``/``hx-delete`` on the same object, since the check is keyed on
    ``request.method`` generally, not a hardcoded "POST") from a non-owner raises
    ``PermissionDenied``, which Django renders as this project's styled 403 page.
    """

    request: HttpRequest

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().visible_to(self.request.user)

    def get_object(self, queryset: QuerySet | None = None) -> Any:
        obj = super().get_object(queryset)
        if not IsOwnerOrReadOnly().has_object_permission(self.request, self, obj):
            raise PermissionDenied(f"You do not have permission to modify {obj!r}.")
        return obj

    def get_form_class(self) -> type[BaseModelForm]:
        """Refuses, at ``manage.py check``/first-request time rather than silently, a
        ``CreateView``/``UpdateView`` whose form exposes ``owner``, ``is_system``,
        ``shared_with``, ``copied_from``, or ``visibility`` as a writable field — the HTML
        counterpart of ``OwnedSerializer`` making those same fields read-only
        (``core/serializers.py``). A bare ``fields = "__all__"`` on a form built over an
        ``OwnedModel`` subclass is exactly how this reopens: the owner (who legitimately passes
        ``IsOwnerOrReadOnly`` above) could then ``POST`` a new ``visibility``/``shared_with``
        straight past ``core/services/sharing.py``'s cascade-refusal check, publishing a
        container with a hole the sharing service exists to prevent.

        Only ``FormMixin``-based views (``CreateView``/``UpdateView``) ever call this — a
        ``ListView``/``DetailView``/``DeleteView`` built on this same mixin has no form and
        never triggers it.
        """
        form_class = super().get_form_class()
        exposed = UNSAFE_OWNED_MODEL_FORM_FIELDS & set(getattr(form_class, "base_fields", {}))
        if exposed:
            raise ImproperlyConfigured(
                f"{type(self).__name__}'s form exposes {sorted(exposed)} as writable field(s). "
                "These bypass core.services.sharing's cascade-refusal check the same way a "
                "writable `visibility` on OwnedSerializer would (see core/serializers.py). "
                "Exclude them from `fields`/`form_class` -- visibility and sharing changes must "
                "go through the /share/ view or API action instead."
            )
        return form_class
