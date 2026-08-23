"""URL routes for the accounts app.

Only the password-change route exists so far. ``ForcePasswordChangeMiddleware`` (subtask
01.5) needs a real, resolvable URL to redirect to; login, logout and profile routes land in
subtask 01.6 along with their real views.
"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("password/change/", views.password_change_placeholder, name="password_change"),
]
