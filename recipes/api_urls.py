"""REST API routes for recipes (``Plan/05-Recipes/design.md``, "API").

Mounted at ``/api/`` by ``config/urls.py``: ``/api/recipes/`` (+ the
``scaled`` / ``flattened`` / ``made`` / ``stats`` detail actions and the
``share`` / ``unshare`` / ``copy`` / ``shares`` actions from ``OwnedViewSetMixin``).

Split from a future ``recipes/urls.py`` (the HTML screens, task 05.10+) the same way
``catalog/api_urls.py`` is split from ``catalog/urls.py``.
"""

from rest_framework.routers import DefaultRouter

from recipes.api import RecipeViewSet

app_name = "recipes_api"

router = DefaultRouter()
router.register("recipes", RecipeViewSet, basename="recipe")

urlpatterns = router.urls
