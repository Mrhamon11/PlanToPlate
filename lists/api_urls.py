"""REST API routes for lists (``Plan/07-Lists-And-Shopping/design.md``, "API").

Mounted at ``/api/`` by ``config/urls.py``: ``/api/lists/`` (+ the ``items`` / ``reorder`` /
``add-dish`` / ``clear-checked`` / ``merge-duplicates`` / ``default-shopping`` actions and the
``share`` / ``unshare`` / ``copy`` / ``shares`` actions from ``OwnedViewSetMixin``).

Split from the future ``lists/urls.py`` (the HTML screens, 07.9+) the same way ``catalog``,
``recipes`` and ``meals`` split their API and HTML route modules.
"""

from rest_framework.routers import DefaultRouter

from lists.api import ListViewSet

app_name = "lists_api"

router = DefaultRouter()
router.register("lists", ListViewSet, basename="list")

urlpatterns = router.urls
