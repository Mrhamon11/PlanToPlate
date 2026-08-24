"""URL configuration for the config project."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import throttled_admin_login

urlpatterns = [
    # Mounted ahead of admin.site.urls (below) so this intercepts admin/login/ before the
    # admin's own login pattern would — see accounts.views.throttled_admin_login. Django's
    # resolver tries patterns in order, so path order here is load-bearing.
    path("admin/login/", throttled_admin_login, name="admin-login-throttled"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("api/auth/", include("accounts.api_urls")),
    path("", include("core.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="api-docs",
    ),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
