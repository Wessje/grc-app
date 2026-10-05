"""
Web addresses for the risk register pages.

- /            list of active risks
- /risks/<n>/  detail page of one risk (n is its internal record number)
"""

from django.urls import path

from risks import views

app_name = "risks"

urlpatterns = [
    path("", views.risk_list, name="risk_list"),
    path("risks/<int:pk>/", views.risk_detail, name="risk_detail"),
]
