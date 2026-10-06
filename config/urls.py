"""
Maps web addresses (URLs) to pages for the whole project.

- /                 the risk register (see risks/urls.py)
- /controls/        the control register (see controls/urls.py)
- /accounts/login/  login page; /accounts/logout/ logs out
- /admin/           Django's admin screen
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("", include("risks.urls")),
    path("controls/", include("controls.urls")),
    # Only login and logout are enabled; Django's password-reset pages are
    # left out because they need email and would be extra public pages.
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
