"""API views for ``/api/auth/`` — see ``Plan/01-Users-And-Auth/design.md``.

Plain ``APIView`` subclasses rather than generics: none of these four actions map onto CRUD
against a queryset, so a generic view would buy nothing but an awkward fit.
"""

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import LoginSerializer, PasswordChangeSerializer, UserSerializer


@method_decorator(sensitive_post_parameters(), name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class LoginAPIView(APIView):
    """Session login for API clients. Unused by the web UI, which has its own login view.

    ``csrf_protect`` is required even though ``APIView.as_view()`` is ``csrf_exempt`` at the
    Django level: DRF's ``SessionAuthentication.enforce_csrf`` only runs for a request that
    *already* carries an authenticated session, so an anonymous login POST would otherwise
    never be checked. Django's test client honours ``_dont_enforce_csrf_checks``, so
    ``APIClient`` calls that don't opt into ``enforce_csrf_checks=True`` are unaffected.

    ``sensitive_post_parameters`` must be the outer decorator (listed first): class decorators
    apply bottom-up, so an inner ``sensitive_post_parameters`` would never run when
    ``csrf_protect`` rejects the request first, leaving the plaintext password unmasked in that
    case.
    """

    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        auth_login(request, serializer.validated_data["user"])
        return Response(UserSerializer(request.user).data)


class LogoutAPIView(APIView):
    """Any authenticated user can always log out — including one on a forced password change.

    Overrides the default permission list, which otherwise 403s via
    ``ForcePasswordChangeAPIPermission``; a session-authenticated request also needs this path
    in ``ForcePasswordChangeMiddleware``'s exemption set (``accounts.middleware
    .api_logout_path``), since the middleware runs before this permission is ever consulted.
    Same reasoning as the HTML ``LogoutView`` exemption (design.md, "The middleware") — a
    forced-reset user must still be able to leave.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        auth_logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeAPIView(APIView):
    """The current user, including ``must_change_password`` — never the password itself."""

    @extend_schema(responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)


@method_decorator(sensitive_post_parameters(), name="dispatch")
class PasswordChangeAPIView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Required immediately after save() (design.md step 4) or this request's own session
        # dies with the others. Guarded on session_key: a token-only request has no session to
        # cycle, and cycle_key() would otherwise create an unused one.
        if request.session.session_key:
            update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
