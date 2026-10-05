"""
Maps web addresses (URLs) to pages for the whole project.

For now only the admin screen exists, at /admin/. While no other pages are
defined, Django shows its welcome page at the home address (in DEBUG mode).
Risk register pages are added from Step 4 of docs/plan.md.
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
