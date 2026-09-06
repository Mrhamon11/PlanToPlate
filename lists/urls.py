"""HTML routes for lists and shopping lists (``Plan/07-Lists-And-Shopping/design.md``, "UI").

Mounted at ``/lists/`` by ``config/urls.py``. The REST API lives separately in
``lists/api_urls.py``, the same split ``catalog`` / ``recipes`` / ``meals`` use.
"""

from django.urls import path

from lists import views

app_name = "lists"

urlpatterns = [
    path("", views.ListIndexView.as_view(), name="index"),
    path("new/", views.ListCreateView.as_view(), name="create"),
    path(
        "add/<str:kind>/<int:obj_pk>/",
        views.AddToListView.as_view(),
        name="add-object",
    ),
    path("<int:pk>/", views.GenericListDetailView.as_view(), name="list-detail"),
    path("<int:pk>/shopping/", views.ShoppingListDetailView.as_view(), name="shopping-detail"),
    path("<int:pk>/delete/", views.ListDeleteView.as_view(), name="delete"),
    path("<int:pk>/add-item/", views.ListItemAddView.as_view(), name="item-add"),
    path("<int:pk>/clear-checked/", views.ListClearCheckedView.as_view(), name="clear-checked"),
    path("<int:pk>/check-all/", views.ListCheckAllView.as_view(), name="check-all"),
    path(
        "<int:pk>/clear-all/confirm/",
        views.ListClearAllConfirmView.as_view(),
        name="clear-all-confirm",
    ),
    path("<int:pk>/clear-all/", views.ListClearAllView.as_view(), name="clear-all"),
    path(
        "<int:pk>/regenerate/confirm/",
        views.ListRegenerateConfirmView.as_view(),
        name="regenerate-confirm",
    ),
    path("<int:pk>/regenerate/", views.ListRegenerateView.as_view(), name="regenerate"),
    path(
        "<int:pk>/items/<int:item_pk>/check/",
        views.ListItemCheckView.as_view(),
        name="item-check",
    ),
    path(
        "<int:pk>/items/<int:item_pk>/edit/",
        views.ListItemEditView.as_view(),
        name="item-edit",
    ),
    path(
        "<int:pk>/items/<int:item_pk>/move/",
        views.ListItemMoveView.as_view(),
        name="item-move",
    ),
    path(
        "<int:pk>/items/<int:item_pk>/delete/",
        views.ListItemDeleteView.as_view(),
        name="item-delete",
    ),
]
