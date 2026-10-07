"""
Web addresses for the control register pages.

- /controls/            list of controls that are not archived
- /controls/new/        form to add a control
- /controls/<n>/        detail page of one control (n is its internal record number)
- /controls/<n>/edit/   form to change that control
"""

from django.urls import path

from controls import views

app_name = "controls"

urlpatterns = [
    path("", views.control_list, name="control_list"),
    path("new/", views.control_create, name="control_create"),
    path("<int:pk>/", views.control_detail, name="control_detail"),
    path("<int:pk>/edit/", views.control_edit, name="control_edit"),
]
