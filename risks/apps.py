"""
Registers the risk register module ("risks" app) with Django.
"""

from django.apps import AppConfig


class RisksConfig(AppConfig):
    name = "risks"
    verbose_name = "Risk register"
