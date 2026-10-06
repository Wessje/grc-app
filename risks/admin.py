"""
Shows risks and risk categories in Django's admin screen (/admin/).

The Risk ID, score and rating are shown but cannot be edited. Risks cannot be
deleted (archive instead, from Step 6), and archived risks are read-only.
Every save is recorded in the change history (see risks/history.py).
"""

from django.contrib import admin

from controls.admin import RiskControlInline
from controls.links import record_control_link_changes, snapshot_control_links
from risks.history import save_risk_with_history
from risks.models import Risk, RiskCategory


@admin.register(RiskCategory)
class RiskCategoryAdmin(admin.ModelAdmin):
    """Admin pages for the category pick-list."""

    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Risk)
class RiskAdmin(admin.ModelAdmin):
    """Admin pages for risks."""

    inlines = [RiskControlInline]
    list_display = [
        "risk_id",
        "title",
        "category",
        "owner",
        "inherent_score",
        "inherent_rating",
        "residual_score",
        "residual_rating",
        "status",
        "is_archived",
    ]
    list_filter = ["status", "category"]
    search_fields = ["risk_id", "title", "description"]
    readonly_fields = [
        "risk_id",
        "inherent_score",
        "inherent_rating",
        "residual_score",
        "residual_rating",
        "archived_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (None, {"fields": ["risk_id", "title", "description", "category", "owner",
                           "risk_source", "date_identified"]}),
        ("Inherent risk", {"fields": ["inherent_likelihood", "inherent_impact",
                                      "inherent_score", "inherent_rating"]}),
        ("Residual risk (after controls)", {"fields": ["residual_likelihood", "residual_impact",
                                                       "residual_score", "residual_rating"]}),
        ("Treatment", {"fields": ["status", "response_type", "response_description"]}),
        ("Risk acceptance (only when the response type is Accept)",
         {"fields": ["accepted_by", "acceptance_date", "acceptance_expiry_date"]}),
        ("Other", {"fields": ["notes", "archived_at", "created_at", "updated_at"]}),
    ]

    @admin.display(description="Inherent rating")
    def inherent_rating(self, risk):
        """Show the rating label (Low/Medium/High/Critical) for a risk."""
        return risk.inherent_rating

    @admin.display(description="Residual rating")
    def residual_rating(self, risk):
        """Show the residual rating, or a dash when it has not been assessed."""
        return risk.residual_rating or "—"

    @admin.display(description="Archived", boolean=True)
    def is_archived(self, risk):
        """Show a tick/cross for whether a risk is archived."""
        return risk.archived_at is not None

    def save_model(self, request, risk, form, change):
        """
        Save a risk from the admin screen, recording its change history.

        Uses the same helper as our own forms, so admin edits are in the
        audit trail too.
        """
        save_risk_with_history(risk, request.user)

    def save_related(self, request, form, formsets, change):
        """
        Save the control links and record what changed in the risk's history.

        The snapshot is taken before the links are saved, then compared with
        the links afterwards.
        """
        risk = form.instance
        before = snapshot_control_links(risk)
        super().save_related(request, form, formsets, change)
        record_control_link_changes(risk, before, snapshot_control_links(risk), request.user)

    def has_change_permission(self, request, risk=None):
        """
        Allow editing only for risks that are not archived.

        Inputs: the web request and the risk being viewed (None on the list
        page). Output: True if the user may edit. An archived risk is shown
        read-only, keeping the record as it was when it left scope.
        """
        if risk is not None and risk.archived_at is not None:
            return False
        return super().has_change_permission(request, risk)

    def has_delete_permission(self, request, risk=None):
        """
        Never allow deleting risks; they are archived instead.

        Output: always False, which also removes the bulk "delete" action.
        """
        return False
