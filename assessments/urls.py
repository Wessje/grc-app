"""
Web addresses for the assessment pages.

- /assessments/      list of assessments that are not archived
- /assessments/<n>/  detail page of one assessment (n is its internal record number)
"""

from django.urls import path

from assessments import views

app_name = "assessments"

urlpatterns = [
    path("", views.assessment_list, name="assessment_list"),
    path("<int:pk>/", views.assessment_detail, name="assessment_detail"),
]
