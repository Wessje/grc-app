"""
Shows processes and solutions in Django's admin screen (/admin/).

The ID is shown but cannot be edited. These records cannot be deleted
(archive instead), and archived ones are read-only.
"""

from django.contrib import admin

from processes.models import Process


@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    """Admin pages for processes and solutions."""

    list_display = ["process_id", "name", "kind", "owner", "is_archived"]
    list_filter = ["kind"]
    search_fields = ["process_id", "name", "description", "owner"]
    readonly_fields = ["process_id", "archived_at", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["process_id", "kind", "name", "description", "owner"]}),
        ("Other", {"fields": ["notes", "archived_at", "created_at", "updated_at"]}),
    ]

    @admin.display(description="Archived", boolean=True)
    def is_archived(self, process):
        """Show a tick/cross for whether this record is archived."""
        return process.archived_at is not None

    def has_change_permission(self, request, process=None):
        """
        Allow editing only for records that are not archived.

        Inputs: the web request and the record being viewed (None on the
        list page). Output: True if the user may edit.
        """
        if process is not None and process.archived_at is not None:
            return False
        return super().has_change_permission(request, process)

    def has_delete_permission(self, request, process=None):
        """
        Never allow deleting these records; they are archived instead.

        Output: always False, which also removes the bulk "delete" action.
        """
        return False
