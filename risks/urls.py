"""
Web addresses for the risk register pages.

- /                    list of active risks
- /archive/            list of archived risks
- /risks/new/          form to create a risk
- /risks/<n>/          detail page of one risk (n is its internal record number)
- /risks/<n>/edit/     form to edit a risk
- /risks/<n>/archive/  confirm and archive a risk
- /risks/<n>/restore/  restore an archived risk (form button only)
"""

from django.urls import path

from risks import views

app_name = "risks"

urlpatterns = [
    path("", views.risk_list, name="risk_list"),
    path("archive/", views.archived_risk_list, name="archived_risk_list"),
    path("risks/new/", views.risk_create, name="risk_create"),
    path("risks/<int:pk>/", views.risk_detail, name="risk_detail"),
    path("risks/<int:pk>/edit/", views.risk_edit, name="risk_edit"),
    path("risks/<int:pk>/archive/", views.risk_archive, name="risk_archive"),
    path("risks/<int:pk>/restore/", views.risk_restore, name="risk_restore"),
]
