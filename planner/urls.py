"""HTML routes for the meal planner (``Plan/08-Meal-Planner/design.md``, "UI").

Mounted at ``/planner/`` by ``config/urls.py``. 08.11 adds the profile editor; 08.12–08.14
add the planner landing page, the generate screen, the saved-plan week grid (with per-slot
lock / reroll / manual-swap HTMX), the shopping-list preview, and the empty-state guidance.
The REST API lives separately in ``planner/api_urls.py``, the same split every other app uses.
"""

from django.urls import path

from planner import views

app_name = "planner"

urlpatterns = [
    path("", views.PlanIndexView.as_view(), name="index"),
    path("profiles/", views.ProfileListView.as_view(), name="profile-list"),
    path("profiles/new/", views.ProfileCreateView.as_view(), name="profile-create"),
    path("profiles/<int:pk>/", views.ProfileUpdateView.as_view(), name="profile-edit"),
    path("profiles/<int:pk>/delete/", views.ProfileDeleteView.as_view(), name="profile-delete"),
    path("plans/new/", views.PlanGenerateView.as_view(), name="plan-generate"),
    path("plans/save/", views.PlanSaveView.as_view(), name="plan-save"),
    path("plans/delete/", views.PlanBulkDeleteView.as_view(), name="plan-bulk-delete"),
    path("plans/<int:pk>/", views.PlanDetailView.as_view(), name="plan-detail"),
    path("plans/<int:pk>/regenerate/", views.PlanRegenerateView.as_view(), name="plan-regenerate"),
    path("plans/<int:pk>/days/", views.PlanDaysView.as_view(), name="plan-days"),
    path("plans/<int:pk>/rename/", views.PlanRenameView.as_view(), name="plan-rename"),
    path("plans/<int:pk>/delete/", views.PlanDeleteView.as_view(), name="plan-delete"),
    path(
        "plans/<int:pk>/share/modal/",
        views.PlanShareModalView.as_view(),
        name="plan-share-modal",
    ),
    path("plans/<int:pk>/share/", views.PlanShareView.as_view(), name="plan-share"),
    path("plans/<int:pk>/unshare/", views.PlanUnshareView.as_view(), name="plan-unshare"),
    path(
        "plans/<int:pk>/entries/<int:entry_pk>/lock/",
        views.PlanEntryLockView.as_view(),
        name="entry-lock",
    ),
    path(
        "plans/<int:pk>/entries/<int:entry_pk>/reroll/",
        views.PlanEntryRerollView.as_view(),
        name="entry-reroll",
    ),
    path(
        "plans/<int:pk>/entries/<int:entry_pk>/swap/",
        views.PlanEntrySwapView.as_view(),
        name="entry-swap",
    ),
    path(
        "plans/<int:pk>/shopping/preview/",
        views.PlanShoppingPreviewView.as_view(),
        name="plan-shopping-preview",
    ),
    path(
        "plans/<int:pk>/shopping/generate/",
        views.PlanShoppingGenerateView.as_view(),
        name="plan-shopping-generate",
    ),
]
