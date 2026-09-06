"""REST API routes for the meal planner (``Plan/08-Meal-Planner/design.md``, "API").

Mounted at ``/api/`` by ``config/urls.py``: ``/api/planner/profiles/`` and
``/api/planner/plans/`` (+ the ``generate`` / ``regenerate`` / ``entries`` / ``reroll`` /
``generate-shopping-list`` / ``preview-shopping-list`` actions and the ``share`` / ``unshare``
/ ``shares`` actions from ``OwnedViewSetMixin``; the inherited ``copy`` action is overridden
to 405 — plan-copy is out of scope, D44).

Split from ``planner/urls.py`` (the HTML screens) the same way every other app splits its API
and HTML route modules.
"""

from rest_framework.routers import DefaultRouter

from planner.api import MealPlanProfileViewSet, MealPlanViewSet

app_name = "planner_api"

router = DefaultRouter()
router.register("planner/profiles", MealPlanProfileViewSet, basename="planner-profile")
router.register("planner/plans", MealPlanViewSet, basename="planner-plan")

urlpatterns = router.urls
