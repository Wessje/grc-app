"""
Web addresses for the risk register pages.

- /                 list of active risks
- /risks/new/       form to create a risk
- /risks/<n>/       detail page of one risk (n is its internal record number)
- /risks/<n>/edit/  form to edit a risk
"""

from django.urls import path

from risks import views

app_name = "risks"

urlpatterns = [
    path("", views.risk_list, name="risk_list"),
    path("risks/new/", views.risk_create, name="risk_create"),
    path("risks/<int:pk>/", views.risk_detail, name="risk_detail"),
    path("risks/<int:pk>/edit/", views.risk_edit, name="risk_edit"),
]
