"""HTML routes for recipes (``Plan/05-Recipes/design.md``, "UI").

Mounted at ``/recipes/`` by ``config/urls.py``. The REST API lives separately in
``recipes/api_urls.py`` (the same split ``catalog`` uses).
"""

from django.urls import path

from recipes import views

app_name = "recipes"

urlpatterns = [
    path("", views.RecipeListView.as_view(), name="recipe-list"),
    path("new/", views.RecipeCreateView.as_view(), name="recipe-create"),
    path("component-row/", views.RecipeComponentRowView.as_view(), name="recipe-component-row"),
    path(
        "typeahead/ingredients/",
        views.RecipeIngredientOptionsView.as_view(),
        name="recipe-ingredient-options",
    ),
    path(
        "typeahead/sub-recipes/",
        views.RecipeSubRecipeOptionsView.as_view(),
        name="recipe-subrecipe-options",
    ),
    path("<int:pk>/", views.RecipeDetailView.as_view(), name="recipe-detail"),
    path("<int:pk>/edit/", views.RecipeUpdateView.as_view(), name="recipe-update"),
    path("<int:pk>/delete/", views.RecipeDeleteView.as_view(), name="recipe-delete"),
    path("<int:pk>/scale/", views.RecipeScaleView.as_view(), name="recipe-scale"),
    path(
        "<int:pk>/component/<int:component_pk>/expand/",
        views.RecipeComponentExpandView.as_view(),
        name="recipe-component-expand",
    ),
    path("<int:pk>/made/", views.RecipeMadeView.as_view(), name="recipe-made"),
    path("<int:pk>/rate/", views.RecipeRateView.as_view(), name="recipe-rate"),
    path("<int:pk>/favorite/", views.RecipeFavoriteView.as_view(), name="recipe-favorite"),
    path("<int:pk>/print/", views.RecipePrintView.as_view(), name="recipe-print"),
    path(
        "<int:pk>/share/modal/",
        views.RecipeShareModalView.as_view(),
        name="recipe-share-modal",
    ),
    path("<int:pk>/share/", views.RecipeShareView.as_view(), name="recipe-share"),
    path("<int:pk>/unshare/", views.RecipeUnshareView.as_view(), name="recipe-unshare"),
    path("<int:pk>/copy/", views.RecipeCopyView.as_view(), name="recipe-copy"),
]
