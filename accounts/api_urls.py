"""``/api/auth/`` routes — see ``Plan/01-Users-And-Auth/design.md``.

Kept separate from ``accounts.urls`` (the HTML routes) rather than merged into one file: the
two are mounted at different prefixes by ``config.urls`` and share no views.
"""

from django.urls import path

from accounts import api

app_name = "accounts_api"

urlpatterns = [
    path("login/", api.LoginAPIView.as_view(), name="login"),
    path("logout/", api.LogoutAPIView.as_view(), name="logout"),
    path("me/", api.MeAPIView.as_view(), name="me"),
    path("password/change/", api.PasswordChangeAPIView.as_view(), name="password-change"),
]
