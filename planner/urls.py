"""HTML routes for the meal planner (``Plan/08-Meal-Planner/design.md``, "UI").

Mounted at ``/planner/`` by ``config/urls.py``. The screens themselves land in 08.11+; this
module exists now so the app is URL-reachable and the namespace is reserved. The REST API
will get its own ``planner/api_urls.py``, the same split the other apps use.
"""

app_name = "planner"

urlpatterns: list = []
