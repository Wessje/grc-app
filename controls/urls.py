"""
Web addresses for the control register pages.

- /controls/        list of controls that are not archived
- /controls/<n>/    detail page of one control (n is its internal record number)
"""

from django.urls import path

from controls import views

app_name = "controls"

urlpatterns = [
    path("", views.control_list, name="control_list"),
    path("<int:pk>/", views.control_detail, name="control_detail"),
]
