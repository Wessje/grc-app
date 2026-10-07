"""
Web addresses for processes and solutions.

- /processes/              list of records that are not archived
- /processes/archive/      list of archived records
- /processes/new/          form to add one
- /processes/<n>/          detail page (n is its internal record number)
- /processes/<n>/edit/     form to change it
- /processes/<n>/archive/  confirm and archive it
- /processes/<n>/restore/  restore an archived one (form button only)
"""

from django.urls import path

from processes import views

app_name = "processes"

urlpatterns = [
    path("", views.process_list, name="process_list"),
    path("archive/", views.archived_process_list, name="archived_process_list"),
    path("new/", views.process_create, name="process_create"),
    path("<int:pk>/", views.process_detail, name="process_detail"),
    path("<int:pk>/edit/", views.process_edit, name="process_edit"),
    path("<int:pk>/archive/", views.process_archive, name="process_archive"),
    path("<int:pk>/restore/", views.process_restore, name="process_restore"),
]
