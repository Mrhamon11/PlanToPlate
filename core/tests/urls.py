"""Test-only URLconf for ``OwnedViewSetMixin`` (03.8) — activated per test module via
``@pytest.mark.urls("core.tests.urls")`` rather than mounted in ``config.urls``, since neither
dummy model exists outside the test database.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.tests.views import DummyDetailView, DummyListView, DummyUpdateView
from core.tests.viewsets import (
    DummyClassLevelAdminViewSet,
    DummyClassLevelAuthenticatedOnlyViewSet,
    DummyNodeViewSet,
    DummyOwnedViewSet,
)

router = DefaultRouter()
router.register("dummy", DummyOwnedViewSet, basename="dummy")
router.register("dummy-nodes", DummyNodeViewSet, basename="dummy-node")
router.register("dummy-admin-only", DummyClassLevelAdminViewSet, basename="dummy-admin-only")
router.register(
    "dummy-authenticated-only",
    DummyClassLevelAuthenticatedOnlyViewSet,
    basename="dummy-authenticated-only",
)

urlpatterns = [
    *router.urls,
    # HTML-side counterparts (03.9), exercising OwnedObjectMixin over the same DummyOwned
    # fixture the DRF routes above use, for core/tests/test_view_mixins.py's "HTML and API
    # agree" test.
    path("dummy-html/", DummyListView.as_view(), name="dummy-html-list"),
    path("dummy-html/<int:pk>/", DummyDetailView.as_view(), name="dummy-html-detail"),
    path("dummy-html/<int:pk>/edit/", DummyUpdateView.as_view(), name="dummy-html-edit"),
    # A plain Django generic view's Http404/PermissionDenied renders templates/404.html/
    # 403.html, both of which extend base.html — whose nav partial reverses accounts:login/
    # profile/logout unconditionally, and core:home. Both apps' URLs must be reachable under
    # this swapped-in test URLconf or that render itself fails with NoReverseMatch, masking the
    # real 404/403 behind an unrelated error.
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),
]
