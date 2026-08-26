"""Test-only URLconf for ``OwnedViewSetMixin`` (03.8) — activated per test module via
``@pytest.mark.urls("core.tests.urls")`` rather than mounted in ``config.urls``, since neither
dummy model exists outside the test database.
"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from core.tests.viewsets import DummyNodeViewSet, DummyOwnedViewSet

router = DefaultRouter()
router.register("dummy", DummyOwnedViewSet, basename="dummy")
router.register("dummy-nodes", DummyNodeViewSet, basename="dummy-node")

urlpatterns = router.urls
