"""
Web addresses for the assessment pages.

- /assessments/            list of assessments that are not archived
- /assessments/new/        form to add an assessment
- /assessments/<n>/        detail page of one assessment (n is its internal record number)
- /assessments/<n>/edit/   form to change that assessment
"""

from django.urls import path

from assessments import views

app_name = "assessments"

urlpatterns = [
    path("", views.assessment_list, name="assessment_list"),
    path("new/", views.assessment_create, name="assessment_create"),
    path("<int:pk>/", views.assessment_detail, name="assessment_detail"),
    path("<int:pk>/edit/", views.assessment_edit, name="assessment_edit"),
]
