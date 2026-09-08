"""``/api/`` routes for core (``Plan/12-Home-Dashboard/design.md``).

Kept separate from ``core.urls`` (the HTML home page and its panel fragments) the same way
every other app splits ``api_urls.py`` from ``urls.py`` — the two mount at different prefixes
in ``config.urls`` and share no views.
"""

from django.urls import path

from core import api

app_name = "core_api"

urlpatterns = [
    path("dashboard/", api.DashboardAPIView.as_view(), name="dashboard"),
]
