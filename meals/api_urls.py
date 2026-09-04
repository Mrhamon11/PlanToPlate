"""REST API routes for meals (``Plan/06-Dishes-And-RecipeBooks/design.md``, "API").

Mounted at ``/api/`` by ``config/urls.py``: ``/api/dishes/`` and ``/api/recipe-books/`` (+ the
detail actions and the ``share`` / ``unshare`` / ``copy`` / ``shares`` actions from
``OwnedViewSetMixin``).

Split from the future ``meals/urls.py`` (the HTML screens, 06.8+) the same way
``catalog`` and ``recipes`` split their API and HTML route modules.
"""

from rest_framework.routers import DefaultRouter

from meals.api import DishViewSet, RecipeBookViewSet

app_name = "meals_api"

router = DefaultRouter()
router.register("dishes", DishViewSet, basename="dish")
router.register("recipe-books", RecipeBookViewSet, basename="recipebook")

urlpatterns = router.urls
