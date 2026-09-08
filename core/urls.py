from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("", views.HomeView.as_view(), name="home"),
    path(
        "dashboard/panel/<str:name>/",
        views.DashboardPanelView.as_view(),
        name="dashboard-panel",
    ),
]
