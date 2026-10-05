"""
The user-account table for people who log in to the GRC tool.

For now it is identical to Django's standard user (username, name, email,
password, permissions). Having our own copy from the start means fields can
be added later (e.g. department) without rebuilding the database.
"""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A person who can log in to the GRC tool."""
