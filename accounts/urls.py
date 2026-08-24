"""HTML URL routes for the accounts app — see ``Plan/01-Users-And-Auth/design.md``.

``LogoutView`` needs no project subclass: Django's own ``http_method_names = ["post",
"options"]`` already answers a GET with 405, which is the whole "POST only" requirement — a
GET logout is CSRF-triggerable from an ``<img>`` tag on any site.
"""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.TempPasswordAwareLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path(
        "password/change/",
        views.ForcedAwarePasswordChangeView.as_view(),
        name="password_change",
    ),
    path("profile/", views.ProfileView.as_view(), name="profile"),
]
