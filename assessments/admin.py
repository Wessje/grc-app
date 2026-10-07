"""
Shows assessments in Django's admin screen (/admin/).

The Assessment ID is shown but cannot be edited. Assessments cannot be
deleted (archive instead), and archived assessments are read-only.
"""

from django.contrib import admin

from assessments.models import Assessment


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    """Admin pages for assessments."""

    list_display = ["assessment_id", "title", "assessment_type", "status", "outcome", "is_archived"]
    list_filter = ["assessment_type", "status", "outcome"]
    search_fields = ["assessment_id", "title", "reviewer", "findings"]
    autocomplete_fields = ["risk", "control"]
    readonly_fields = ["assessment_id", "archived_at", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["assessment_id", "title", "assessment_type", "review_date", "reviewer", "status"]}),
        ("Subject", {"fields": ["risk", "control"],
                     "description": "A control test names a control. A risk review names a risk."}),
        ("Result", {"fields": ["outcome", "findings", "evidence", "next_review_date"]}),
        ("Other", {"fields": ["notes", "archived_at", "created_at", "updated_at"]}),
    ]

    @admin.display(description="Archived", boolean=True)
    def is_archived(self, assessment):
        """Show a tick/cross for whether an assessment is archived."""
        return assessment.archived_at is not None

    def has_change_permission(self, request, assessment=None):
        """
        Allow editing only for assessments that are not archived.

        Inputs: the web request and the assessment being viewed (None on the
        list page). Output: True if the user may edit. An archived assessment
        is shown read-only.
        """
        if assessment is not None and assessment.archived_at is not None:
            return False
        return super().has_change_permission(request, assessment)

    def has_delete_permission(self, request, assessment=None):
        """
        Never allow deleting assessments; they are archived instead.

        Output: always False, which also removes the bulk "delete" action.
        """
        return False
