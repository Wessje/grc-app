"""
Shows user accounts in Django's admin screen, with the standard user-management
pages (add user, change password, permissions).
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User

admin.site.register(User, UserAdmin)
