"""HTML routes for the ingredient catalog (``Plan/04-Units-And-Ingredients/design.md``, "UI").

Mounted at ``/ingredients/`` by ``config/urls.py``. The REST API lives separately in
``catalog/api_urls.py``.
"""

from django.urls import path

from catalog import views

app_name = "catalog"

urlpatterns = [
    path("", views.IngredientListView.as_view(), name="ingredient-list"),
    path("new/", views.IngredientCreateView.as_view(), name="ingredient-create"),
    path("quick-add/", views.IngredientQuickAddView.as_view(), name="ingredient-quick-add"),
    path("<int:pk>/", views.IngredientDetailView.as_view(), name="ingredient-detail"),
    path("<int:pk>/edit/", views.IngredientUpdateView.as_view(), name="ingredient-update"),
    path("<int:pk>/delete/", views.IngredientDeleteView.as_view(), name="ingredient-delete"),
    path("<int:pk>/copy/", views.IngredientCopyView.as_view(), name="ingredient-copy"),
    path(
        "<int:pk>/share/modal/",
        views.IngredientShareModalView.as_view(),
        name="ingredient-share-modal",
    ),
    path("<int:pk>/share/", views.IngredientShareView.as_view(), name="ingredient-share"),
    path("<int:pk>/unshare/", views.IngredientUnshareView.as_view(), name="ingredient-unshare"),
]
