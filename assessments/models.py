"""
Assessments: a review of one risk, a test of one control, or a review of
one process or solution.

A process or solution review records an outcome for each control in scope,
and can reassess the risks already linked to that process. Creating or
updating a risk from that review is done in assessments/effects.py, and
only when the review is saved as Complete. A satisfactory control test
does not create a risk and does not close one.

This file is the central definition of an assessment, so the admin screen
and our own forms enforce these rules.
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction

from risks.models import IMPACT_CHOICES, LIKELIHOOD_CHOICES


class Assessment(models.Model):
    """One review of a single risk, or one test of a single control."""

    # Order used when summarising a process review: worst result first.
    _LINE_OUTCOMES = (
        ("unsatisfactory", "unsatisfactory"),
        ("partial", "partially satisfactory"),
        ("satisfactory", "satisfactory"),
    )

    class AssessmentType(models.TextChoices):
        CONTROL_TEST = "control_test", "Control test"
        RISK_REVIEW = "risk_review", "Risk review"
        PROCESS_REVIEW = "process_review", "Process or solution review"

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
    # Set only for a process or solution review. The controls and risks
    # covered by that review are the related lines, not this field.
    process = models.ForeignKey(
        "processes.Process",
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

    def list_outcome(self):
        """
        The result to show in a list.

        A control test or a risk review uses its own outcome. A process or
        solution review has no outcome of its own: it counts the control
        lines that were included, worst first (unsatisfactory, then partial,
        then satisfactory). A control left out of the review is not counted.
        When no included control has an outcome yet, the result is a dash.

        Input: this assessment. Output: a short label, for example
        "Satisfactory" or "1 unsatisfactory, 2 satisfactory".
        """
        if self.assessment_type != self.AssessmentType.PROCESS_REVIEW:
            return self.get_outcome_display() or "—"
        # The list page counts these in one query (see with_outcome_counts).
        # Anywhere else, count the lines here.
        if getattr(self, "unsatisfactory_count", None) is None:
            counts = {outcome: 0 for outcome, _label in self._LINE_OUTCOMES}
            for outcome in self.control_results.filter(include=True).exclude(outcome="").values_list(
                "outcome", flat=True
            ):
                if outcome in counts:
                    counts[outcome] += 1
        else:
            counts = {
                self.Outcome.UNSATISFACTORY: self.unsatisfactory_count,
                self.Outcome.PARTIAL: self.partial_count,
                self.Outcome.SATISFACTORY: self.satisfactory_count,
            }
        parts = [
            f"{counts[outcome]} {label}"
            for outcome, label in self._LINE_OUTCOMES
            if counts[outcome]
        ]
        return ", ".join(parts) if parts else "—"

    def clean(self):
        """
        Check the rules that involve more than one field.

        Input: the assessment as filled in. Output: nothing if valid;
        otherwise a ValidationError listing each problem next to the field
        it concerns. A control test must name a control and no risk. A risk
        review must name a risk and no control. A process or solution review
        names that process, and records each control and risk on its own
        lines. The outcome, finding and evidence on this record are required
        only once a single-subject assessment is Complete, and the outcome
        must stay empty while it is still Planned.
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
        elif self.assessment_type == self.AssessmentType.PROCESS_REVIEW:
            if self.process_id is None:
                errors["process"] = "Choose the process or solution this review covers."
            if self.risk_id is not None:
                errors["risk"] = "Name each risk on its own line, not on the review itself."
            if self.control_id is not None:
                errors["control"] = "Name each control on its own line, not on the review itself."
        if self.assessment_type != self.AssessmentType.PROCESS_REVIEW and self.process_id is not None:
            errors["process"] = "Only a process or solution review is linked to a process."
        return errors

    def _check_result(self):
        """Return errors for the outcome, finding and evidence."""
        errors = {}
        if self.assessment_type == self.AssessmentType.PROCESS_REVIEW:
            if self.outcome:
                errors["outcome"] = (
                    "Record each control's outcome on its own line, not on the review itself."
                )
            return errors
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


class AssessedControl(models.Model):
    """
    One control tested inside a process or solution review.

    The outcome is about this control in this process only. The same control
    can pass in one process and fail in another. Likelihood and impact are
    filled in only when the outcome is not satisfactory, because that is
    when a risk is created or updated. `risk` remembers which risk that was,
    so saving the review again updates the same risk.
    """

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="control_results"
    )
    control = models.ForeignKey(
        "controls.Control", on_delete=models.PROTECT, related_name="process_assessment_lines"
    )
    include = models.BooleanField(
        default=False,
        help_text="Untick to leave this control out of this review.",
    )
    outcome = models.CharField(max_length=20, choices=Assessment.Outcome, blank=True)
    findings = models.TextField(blank=True)
    evidence = models.TextField(blank=True)
    likelihood = models.PositiveSmallIntegerField(
        choices=LIKELIHOOD_CHOICES, null=True, blank=True
    )
    impact = models.PositiveSmallIntegerField(
        choices=IMPACT_CHOICES, null=True, blank=True
    )
    category = models.ForeignKey(
        "risks.RiskCategory", null=True, blank=True, on_delete=models.PROTECT
    )
    risk = models.ForeignKey(
        "risks.Risk",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_control_lines",
    )

    class Meta:
        ordering = ["control__control_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "control"], name="one_control_line_per_assessment"
            ),
        ]

    def __str__(self):
        return f"{self.control} in {self.assessment}"


class AssessedRisk(models.Model):
    """
    One risk on a process or solution review.

    `risk` is empty when this line is a new risk that has not been written
    to the register yet (the review is still Planned). The other fields are
    the same ones used when registering a risk, so the review can add a risk
    or update one. Likelihood and impact here are the inherent scores.
    `close_risk` is set when the status on this line is Closed. A
    satisfactory control test never closes a risk by itself.
    """

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="risk_reviews"
    )
    risk = models.ForeignKey(
        "risks.Risk",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reassessments",
    )
    include = models.BooleanField(
        default=False,
        help_text="Tick to assess this risk in this review.",
    )
    findings = models.TextField(blank=True)
    evidence = models.TextField(blank=True)
    # Inherent scores. Kept under these names so earlier reviews still load.
    likelihood = models.PositiveSmallIntegerField(
        choices=LIKELIHOOD_CHOICES, null=True, blank=True
    )
    impact = models.PositiveSmallIntegerField(
        choices=IMPACT_CHOICES, null=True, blank=True
    )
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        "risks.RiskCategory", null=True, blank=True, on_delete=models.PROTECT
    )
    owner = models.CharField(max_length=200, blank=True)
    risk_source = models.CharField(max_length=200, blank=True)
    date_identified = models.DateField(null=True, blank=True)
    residual_likelihood = models.PositiveSmallIntegerField(
        choices=LIKELIHOOD_CHOICES, null=True, blank=True
    )
    residual_impact = models.PositiveSmallIntegerField(
        choices=IMPACT_CHOICES, null=True, blank=True
    )
    risk_status = models.CharField(max_length=20, blank=True)
    response_type = models.CharField(max_length=20, blank=True)
    response_description = models.TextField(blank=True)
    accepted_by = models.CharField(max_length=200, blank=True)
    acceptance_date = models.DateField(null=True, blank=True)
    acceptance_expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    close_risk = models.BooleanField(
        "close this risk",
        default=False,
        help_text="Set when the status on this line is Closed.",
    )

    class Meta:
        ordering = ["risk__risk_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "risk"], name="one_risk_line_per_assessment"
            ),
        ]

    def __str__(self):
        if self.risk_id:
            return f"{self.risk} in {self.assessment}"
        return f"{self.title or 'New risk'} in {self.assessment}"
