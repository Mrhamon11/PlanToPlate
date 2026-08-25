"""Object-level permission classes for owned resources (design.md, "Permissions").

DRF's ``get_object()`` only ever calls ``has_object_permission`` against a row that
``get_queryset()`` already returned via ``.visible_to(user)`` — an invisible object never
reaches these checks at all; it 404s before any permission class runs. The queryset filter is
therefore the primary defence and these classes are the secondary one, closing the gap between
"visible" and "writable" (MILESTONES.md section 6).

That said, every class here fails closed on its own, without relying on the queryset having done
its job first: each checks ``request.user.is_authenticated`` before touching ``obj``, and
``IsOwnerOrReadOnly``'s safe-method branch re-derives visibility through ``visible_to()`` rather
than allowing it unconditionally. A permission class that only holds *because* some call site's
``get_queryset()`` filtered correctly is not a secondary defence — it is the same defence typed
twice, and a viewset that forgets ``.visible_to()`` would otherwise have nothing left to catch
it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.permissions import SAFE_METHODS, BasePermission

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

    from core.models import OwnedModel


def _is_visible(user, obj: OwnedModel) -> bool:
    """Whether ``user`` can see ``obj``, via the same ``visible_to()`` every queryset uses —
    never a hand-rolled re-derivation of the visibility rule (design.md: "a filter written twice
    is a filter that will diverge exactly once, silently, in the direction of leaking").
    """
    return type(obj)._default_manager.visible_to(user).filter(pk=obj.pk).exists()


def _owns(user, obj: OwnedModel) -> bool:
    return obj.owner_id is not None and obj.owner_id == user.pk


class IsOwnerOrReadOnly(BasePermission):
    """Safe methods are allowed only if the object is visible to the requester; unsafe methods
    are owner-only, and never allowed on an ``is_system`` object regardless of who is asking.
    """

    def has_object_permission(self, request: Request, view: APIView, obj: OwnedModel) -> bool:
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return _is_visible(request.user, obj)
        if obj.is_system:
            return False
        return _owns(request.user, obj)


class IsOwner(BasePermission):
    """Owner-only, no safe-method carve-out — for endpoints where even reading is sensitive,
    such as the ``/shares/`` audience list (design.md: "the audience list is itself
    sensitive").
    """

    def has_object_permission(self, request: Request, view: APIView, obj: OwnedModel) -> bool:
        if not request.user.is_authenticated:
            return False
        if obj.is_system:
            return False
        return _owns(request.user, obj)


class CanCopy(BasePermission):
    """The object must be visible to the requester: owned by them, a system object, public, or
    explicitly shared with them. In practice ``get_queryset()`` has already guaranteed this by
    the time ``has_object_permission`` runs — this class exists to give the rule its own name
    so it is directly testable, per design.md: "if you can see it, you can copy it".
    """

    def has_object_permission(self, request: Request, view: APIView, obj: OwnedModel) -> bool:
        if not request.user.is_authenticated:
            return False
        return _is_visible(request.user, obj)
