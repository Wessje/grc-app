"""
Shows controls in Django's admin screen (/admin/).

The Control ID is shown but cannot be edited. Controls cannot be deleted
(archive instead), and archived controls are read-only.
"""

from django.contrib import admin

from controls.models import Control, RiskControl


@admin.register(Control)
class ControlAdmin(admin.ModelAdmin):
    """Admin pages for controls."""

    list_display = ["control_id", "title", "owner", "control_type", "status", "is_archived"]
    list_filter = ["control_type", "status"]
    search_fields = ["control_id", "title", "description", "owner"]
    readonly_fields = ["control_id", "archived_at", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["control_id", "title", "description", "owner",
                           "control_type", "status"]}),
        ("Other", {"fields": ["notes", "archived_at", "created_at", "updated_at"]}),
    ]

    @admin.display(description="Archived", boolean=True)
    def is_archived(self, control):
        """Show a tick/cross for whether a control is archived."""
        return control.archived_at is not None

    def has_change_permission(self, request, control=None):
        """
        Allow editing only for controls that are not archived.

        Inputs: the web request and the control being viewed (None on the
        list page). Output: True if the user may edit. An archived control is
        shown read-only, keeping the record as it was when it left scope.
        """
        if control is not None and control.archived_at is not None:
            return False
        return super().has_change_permission(request, control)

    def has_delete_permission(self, request, control=None):
        """
        Never allow deleting controls; they are archived instead.

        Output: always False, which also removes the bulk "delete" action.
        """
        return False


class RiskControlInline(admin.TabularInline):
    """Controls linked to one risk, edited on the risk's admin page."""

    model = RiskControl
    extra = 1
    autocomplete_fields = ["control"]
    fields = ["control", "effectiveness"]
