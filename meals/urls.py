"""HTML routes for dishes and recipe books (``Plan/06-Dishes-And-RecipeBooks/design.md``,
"UI").

Mounted at the site root by ``config/urls.py`` (patterns carry their own ``dishes/`` /
``books/`` prefix), the same way ``core.urls`` is. The REST API lives separately in
``meals/api_urls.py``.
"""

from django.urls import path

from meals import views

app_name = "meals"

urlpatterns = [
    # --- dishes ---
    path("dishes/", views.DishListView.as_view(), name="dish-list"),
    path("dishes/new/", views.DishCreateView.as_view(), name="dish-create"),
    path(
        "dishes/component-row/",
        views.DishComponentRowView.as_view(),
        name="dish-component-row",
    ),
    path(
        "dishes/typeahead/recipes/",
        views.DishRecipeOptionsView.as_view(),
        name="dish-recipe-options",
    ),
    path("dishes/<int:pk>/", views.DishDetailView.as_view(), name="dish-detail"),
    path("dishes/<int:pk>/edit/", views.DishUpdateView.as_view(), name="dish-update"),
    path("dishes/<int:pk>/delete/", views.DishDeleteView.as_view(), name="dish-delete"),
    path("dishes/<int:pk>/made/", views.DishMadeView.as_view(), name="dish-made"),
    path("dishes/<int:pk>/rate/", views.DishRateView.as_view(), name="dish-rate"),
    path("dishes/<int:pk>/favorite/", views.DishFavoriteView.as_view(), name="dish-favorite"),
    path(
        "dishes/<int:pk>/share/modal/",
        views.DishShareModalView.as_view(),
        name="dish-share-modal",
    ),
    path("dishes/<int:pk>/share/", views.DishShareView.as_view(), name="dish-share"),
    path("dishes/<int:pk>/unshare/", views.DishUnshareView.as_view(), name="dish-unshare"),
    path("dishes/<int:pk>/copy/", views.DishCopyView.as_view(), name="dish-copy"),
    # --- recipe books ---
    path("books/", views.RecipeBookListView.as_view(), name="book-list"),
    path("books/new/", views.RecipeBookCreateView.as_view(), name="book-create"),
    path(
        "books/add-to-book/<int:recipe_pk>/",
        views.RecipeAddToBookView.as_view(),
        name="recipe-add-to-book",
    ),
    path("books/<int:pk>/", views.RecipeBookDetailView.as_view(), name="book-detail"),
    path("books/<int:pk>/edit/", views.RecipeBookUpdateView.as_view(), name="book-update"),
    path("books/<int:pk>/delete/", views.RecipeBookDeleteView.as_view(), name="book-delete"),
    path("books/<int:pk>/add/", views.BookAddRecipeView.as_view(), name="book-add-recipe"),
    path(
        "books/<int:pk>/remove/<int:recipe_pk>/confirm/",
        views.BookRemoveRecipeConfirmView.as_view(),
        name="book-remove-recipe-confirm",
    ),
    path(
        "books/<int:pk>/remove/<int:recipe_pk>/",
        views.BookRemoveRecipeView.as_view(),
        name="book-remove-recipe",
    ),
    path(
        "books/<int:pk>/move/<int:recipe_pk>/",
        views.BookEntryMoveView.as_view(),
        name="book-entry-move",
    ),
    path("books/<int:pk>/ordering/", views.BookOrderingView.as_view(), name="book-ordering"),
    path(
        "books/<int:pk>/copy/confirm/",
        views.BookCopyConfirmView.as_view(),
        name="book-copy-confirm",
    ),
    path("books/<int:pk>/copy/", views.BookCopyView.as_view(), name="book-copy"),
    path(
        "books/<int:pk>/share/modal/",
        views.RecipeBookShareModalView.as_view(),
        name="book-share-modal",
    ),
    path("books/<int:pk>/share/", views.RecipeBookShareView.as_view(), name="book-share"),
    path("books/<int:pk>/unshare/", views.RecipeBookUnshareView.as_view(), name="book-unshare"),
]
