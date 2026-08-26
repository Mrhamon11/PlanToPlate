"""Throwaway viewsets exercising ``OwnedViewSetMixin`` against ``core.tests.models`` — see that
module's docstring for why these are test-only. Wired only via ``core/tests/urls.py``, activated
per test module with ``@pytest.mark.urls("core.tests.urls")`` rather than mounted in
``config.urls``, since neither dummy model exists outside the test database.
"""

from __future__ import annotations

from rest_framework import viewsets

from core.tests.models import DummyNode, DummyOwned
from core.tests.serializers import DummyNodeSerializer, DummySerializer
from core.viewsets import OwnedViewSetMixin


class DummyOwnedViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = DummyOwned.objects.all()
    serializer_class = DummySerializer


class DummyNodeViewSet(OwnedViewSetMixin, viewsets.ModelViewSet):
    queryset = DummyNode.objects.all()
    serializer_class = DummyNodeSerializer
