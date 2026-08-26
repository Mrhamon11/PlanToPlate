"""Throwaway viewsets exercising ``OwnedViewSetMixin`` against ``core.tests.models`` — see that
module's docstring for why these are test-only. Wired only via ``core/tests/urls.py``, activated
per test module with ``@pytest.mark.urls("core.tests.urls")`` rather than mounted in
``config.urls``, since neither dummy model exists outside the test database.
"""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.tests.models import DummyNode, DummyOwned
from core.tests.serializers import DummyNodeSerializer, DummySerializer
from core.viewsets import OwnedViewSetMixin


class DummyOwnedViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = DummyOwned.objects.all()
    serializer_class = DummySerializer

    # Exercises core/tests/test_idor.py's proof that an @action's own permission_classes
    # kwarg is actually composed into get_permissions() (03.8a rework, security finding 2) --
    # not the mixin's per-action IsOwner/CanCopy default, and not silently dropped.
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def admin_only(self, request: Request, pk: str | None = None) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


class DummyNodeViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = DummyNode.objects.all()
    serializer_class = DummyNodeSerializer


class DummyClassLevelAdminViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    """Exercises the class-attribute half of the same proof: a subclass's own
    ``permission_classes`` declaration must also be composed additively, not ignored in favour
    of the mixin's per-action default.
    """

    queryset = DummyOwned.objects.all()
    serializer_class = DummySerializer
    permission_classes = [IsAdminUser]


class DummyClassLevelAuthenticatedOnlyViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    """The 03.8a-rework-iteration-3 review's exact repro (blocking finding 1): a viewset
    declaring the single most common ``permission_classes`` line in DRF —
    ``[IsAuthenticated]`` — reads as *tightening* ``IsOwnerOrReadOnly``/``IsOwner``, not
    replacing them. Unlike ``DummyClassLevelAdminViewSet`` (whose ``IsAdminUser`` already
    denies every non-staff user by itself, so it cannot prove the mixin's own baseline
    survived), ``IsAuthenticated`` grants nothing beyond what ``IsAuthenticated`` in
    ``DEFAULT_PERMISSION_CLASSES`` already grants -- so if the mixin's own
    ``IsOwnerOrReadOnly``/``IsOwner`` baseline is dropped, a read-only sharee can ``DELETE`` the
    object and read its ``/shares/`` audience list. Only a genuinely additive composition
    denies both.
    """

    queryset = DummyOwned.objects.all()
    serializer_class = DummySerializer
    permission_classes = [IsAuthenticated]
