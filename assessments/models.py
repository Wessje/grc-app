"""
Assessments: a periodic review of one risk, or a test of one control.

Each row records the finding, the evidence that was looked at, and the
outcome of that review. It does not change the risk score, the residual
rating, or how effective a control is for a risk. Those stay separate
judgments.

This file is the central definition of an assessment, so the admin screen
and our own forms enforce these rules.
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction


class Assessment(models.Model):
    """One review of a single risk, or one test of a single control."""

    class AssessmentType(models.TextChoices):
        CONTROL_TEST = "control_test", "Control test"
        RISK_REVIEW = "risk_review", "Risk review"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        COMPLETE = "complete", "Complete"

    class Outcome(models.TextChoices):
        SATISFACTORY = "satisfactory", "Satisfactory"
        PARTIAL = "partial", "Partially satisfactory"
        UNSATISFACTORY = "unsatisfactory", "Unsatisfactory"

    # Generated after the first save (see `save`); empty until then.
    assessment_id = models.CharField(
        "assessment ID", max_length=20, unique=True, null=True, blank=True, editable=False
    )
    title = models.CharField(max_length=200)
    assessment_type = models.CharField("type", max_length=20, choices=AssessmentType)
    # Exactly one of these is set, matching the type. See `clean`.
    risk = models.ForeignKey(
        "risks.Risk",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    control = models.ForeignKey(
        "controls.Control",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    review_date = models.DateField()
    reviewer = models.CharField(max_length=200, help_text="Person or role.")
    status = models.CharField(max_length=20, choices=Status, default=Status.PLANNED)
    # Empty until the review is finished. Required once the status is Complete.
    outcome = models.CharField(max_length=20, choices=Outcome, blank=True)
    findings = models.TextField(blank=True)
    evidence = models.TextField(
        blank=True,
        help_text="What was looked at. A written description, not an uploaded file.",
    )
    next_review_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Empty means active. Set when archived, cleared when restored.
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.assessment_id or 'New assessment'}: {self.title}"

    def clean(self):
        """
        Check the rules that involve more than one field.

        Input: the assessment as filled in. Output: nothing if valid;
        otherwise a ValidationError listing each problem next to the field
        it concerns. A control test must name a control and no risk. A risk
        review must name a risk and no control. The outcome, finding and
        evidence are required only once the status is Complete, and the
        outcome must stay empty while the assessment is still Planned.
        """
        errors = {}
        errors.update(self._check_subject())
        errors.update(self._check_result())
        if (
            self.review_date
            and self.next_review_date
            and self.next_review_date <= self.review_date
        ):
            errors["next_review_date"] = "The next review date must be after the review date."
        if errors:
            raise ValidationError(errors)

    def _check_subject(self):
        """Return errors when the linked risk or control does not match the type."""
        errors = {}
        if self.assessment_type == self.AssessmentType.CONTROL_TEST:
            if self.control_id is None:
                errors["control"] = "Choose the control this test covers."
            if self.risk_id is not None:
                errors["risk"] = "A control test is linked to a control, not a risk."
        elif self.assessment_type == self.AssessmentType.RISK_REVIEW:
            if self.risk_id is None:
                errors["risk"] = "Choose the risk this review covers."
            if self.control_id is not None:
                errors["control"] = "A risk review is linked to a risk, not a control."
        return errors

    def _check_result(self):
        """Return errors for the outcome, finding and evidence."""
        errors = {}
        if self.status == self.Status.COMPLETE:
            if not self.outcome:
                errors["outcome"] = "Record the outcome when the assessment is complete."
            if not self.findings.strip():
                errors["findings"] = "Record the finding when the assessment is complete."
            if not self.evidence.strip():
                errors["evidence"] = "Describe the evidence when the assessment is complete."
        elif self.outcome:
            errors["outcome"] = "Only fill this in when the status is Complete."
        return errors

    def save(self, *args, **kwargs):
        """
        Save the assessment and assign an Assessment ID on the first save.

        The ID is based on the database's record number, which SQLite never
        hands out twice, so an ID is never reused. That number only exists
        after the first save, so a new assessment is saved, then given its ID.
        Both happen in one transaction: either both succeed or neither.
        """
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.assessment_id:
                self.assessment_id = f"ASMT-{self.pk:04d}"
                super().save(update_fields=["assessment_id"])
