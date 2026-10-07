"""
Web addresses for the control register pages.

- /controls/              list of controls that are not archived
- /controls/archive/      list of archived controls
- /controls/new/          form to add a control
- /controls/<n>/          detail page of one control (n is its internal record number)
- /controls/<n>/edit/     form to change that control
- /controls/<n>/archive/  confirm and archive a control
- /controls/<n>/restore/  restore an archived control (form button only)
"""

from django.urls import path

from controls import views

app_name = "controls"

urlpatterns = [
    path("", views.control_list, name="control_list"),
    path("archive/", views.archived_control_list, name="archived_control_list"),
    path("new/", views.control_create, name="control_create"),
    path("<int:pk>/", views.control_detail, name="control_detail"),
    path("<int:pk>/edit/", views.control_edit, name="control_edit"),
    path("<int:pk>/archive/", views.control_archive, name="control_archive"),
    path("<int:pk>/restore/", views.control_restore, name="control_restore"),
]
