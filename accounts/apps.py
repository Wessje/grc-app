"""
Registers the user-accounts module ("accounts" app) with Django.
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "User accounts"
