"""DRF-side counterpart to ``ForcePasswordChangeMiddleware``.

See ``Plan/01-Users-And-Auth/design.md``, "Temp password flow" step 3. DRF authenticates a
token inside ``APIView.initial()``, which runs *after* the middleware — at that point
``request.user`` is still ``AnonymousUser`` for a token-bearing request, so a
``must_change_password=True`` token holder would otherwise get unrestricted API access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission

from accounts.middleware import api_password_change_path

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class ForcePasswordChangeAPIPermission(BasePermission):
    """Blocks every API request from a ``must_change_password=True`` user except the one
    endpoint that can clear the condition. Exact-path, mirroring the middleware's own rule —
    a prefix match on ``/api/auth/`` would also exempt ``/api/auth/me/``.
    """

    message = "password_change_required"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user.is_authenticated or not user.must_change_password:
            return True
        return request.path == api_password_change_path()
