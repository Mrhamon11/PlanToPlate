"""View mixins shared by every screen (design.md, "Base view helpers").

``HtmxTemplateMixin`` and ``MessageMixin`` are the two pieces every HTMX-backed view needs;
``OwnedObjectMixin`` is a deliberately empty placeholder so task 03's views land onto an
existing name instead of each later task inventing its own.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.http import HttpRequest
from django.template.loader import render_to_string


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
    """Placeholder for task 03 (Ownership & Sharing).

    Declared now, empty, so views written in tasks 04+ can already compose against
    ``core.mixins.OwnedObjectMixin`` — task 03 fills this in with the ``.visible_to(user)``
    queryset scoping and object-level write checks described in ``MILESTONES.md`` section 6,
    rather than each later view inventing its own ownership filter in the meantime.
    """
