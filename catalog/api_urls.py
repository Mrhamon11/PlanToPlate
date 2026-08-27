"""REST API routes for the catalog (``Plan/04-Units-And-Ingredients/design.md``, "API").

Mounted at ``/api/`` by ``config/urls.py``:
``/api/units/`` · ``/api/units/convert/`` · ``/api/tags/`` · ``/api/ingredients/`` (+ the
``share``/``unshare``/``copy``/``shares`` detail actions from ``OwnedViewSetMixin``).
"""

from rest_framework.routers import DefaultRouter

from catalog.api import IngredientViewSet, TagViewSet, UnitViewSet

app_name = "catalog_api"

router = DefaultRouter()
router.register("units", UnitViewSet, basename="unit")
router.register("tags", TagViewSet, basename="tag")
router.register("ingredients", IngredientViewSet, basename="ingredient")

urlpatterns = router.urls
