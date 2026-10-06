"""
Database tables for the risk register: RiskCategory, Risk and RiskChange
(the change history).

This file is the central definition of a risk. The validation rules live here
(in `Risk.clean`), so the admin screen and our own forms enforce exactly the
same rules. The scoring scales and rating bands are also defined here, in one
place, so they are easy to adjust later.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

# --- Scoring scales --------------------------------------------------------

# Each scale value is shown with its label, e.g. "3 – Possible", so everyone
# scores against the same definitions.
LIKELIHOOD_CHOICES = [
    (1, "1 – Rare"),
    (2, "2 – Unlikely"),
    (3, "3 – Possible"),
    (4, "4 – Likely"),
    (5, "5 – Almost certain"),
]

IMPACT_CHOICES = [
    (1, "1 – Insignificant"),
    (2, "2 – Minor"),
    (3, "3 – Moderate"),
    (4, "4 – Major"),
    (5, "5 – Severe"),
]

# Rating bands: each entry is (highest score in the band, rating label).
# Scores run from 1 to 25 (likelihood × impact). Adjust the bands here only.
RATING_BANDS = [
    (4, "Low"),
    (9, "Medium"),
    (16, "High"),
    (25, "Critical"),
]


def calculate_inherent_score(likelihood, impact):
    """
    Calculate the inherent risk score.

    Inputs: likelihood and impact, each a whole number from 1 to 5.
    Output: likelihood × impact, a whole number from 1 to 25.
    """
    return likelihood * impact


def rating_for_score(score):
    """
    Turn a risk score into a rating label.

    Input: a score from 1 to 25.
    Output: "Low", "Medium", "High" or "Critical", using RATING_BANDS.
    """
    for highest_score_in_band, rating in RATING_BANDS:
        if score <= highest_score_in_band:
            return rating
    return RATING_BANDS[-1][1]


def score_range_for_rating(rating):
    """
    Return the lowest and highest score that give a rating.

    Input: a rating label, e.g. "High". Output: (lowest, highest), e.g. (10, 16),
    worked out from RATING_BANDS so it follows any change to the bands.
    """
    lowest = 1
    for highest_score_in_band, band_rating in RATING_BANDS:
        if band_rating == rating:
            return lowest, highest_score_in_band
        lowest = highest_score_in_band + 1
    raise ValueError(f"Unknown rating: {rating}")


# --- Tables ----------------------------------------------------------------


class RiskCategory(models.Model):
    """A category from the pick-list, e.g. Cyber or Operational."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "risk categories"

    def __str__(self):
        return self.name


class Risk(models.Model):
    """One entry in the risk register."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_TREATMENT = "in_treatment", "In treatment"
        MONITORING = "monitoring", "Monitoring"
        CLOSED = "closed", "Closed"

    class ResponseType(models.TextChoices):
        MITIGATE = "mitigate", "Mitigate"
        ACCEPT = "accept", "Accept"
        TRANSFER = "transfer", "Transfer"
        AVOID = "avoid", "Avoid"

    # Generated after the first save (see `save`); empty until then.
    risk_id = models.CharField(
        "risk ID", max_length=20, unique=True, null=True, blank=True, editable=False
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    # PROTECT: a category that is still used by a risk cannot be deleted.
    category = models.ForeignKey(RiskCategory, on_delete=models.PROTECT)
    owner = models.CharField(max_length=200, help_text="Person or role.")
    risk_source = models.CharField(
        max_length=200,
        help_text="Where the risk resides, e.g. a process or a solution/system.",
    )
    date_identified = models.DateField(default=timezone.localdate)

    inherent_likelihood = models.PositiveSmallIntegerField(choices=LIKELIHOOD_CHOICES)
    inherent_impact = models.PositiveSmallIntegerField(choices=IMPACT_CHOICES)
    # Calculated in `save`, never entered by hand.
    inherent_score = models.PositiveSmallIntegerField(editable=False, blank=True)

    # After controls. Both empty until someone assesses the residual risk;
    # filling in one requires the other. The score is calculated in `save`.
    residual_likelihood = models.PositiveSmallIntegerField(
        choices=LIKELIHOOD_CHOICES,
        null=True,
        blank=True,
        help_text="After controls. Leave both residual scores blank until this has been assessed.",
    )
    residual_impact = models.PositiveSmallIntegerField(
        choices=IMPACT_CHOICES, null=True, blank=True
    )
    residual_score = models.PositiveSmallIntegerField(
        null=True, blank=True, editable=False
    )

    status = models.CharField(max_length=20, choices=Status, default=Status.OPEN)

    response_type = models.CharField(
        "risk response type", max_length=20, choices=ResponseType, blank=True
    )
    response_description = models.TextField("risk response description", blank=True)

    # Only used when the response type is Accept.
    accepted_by = models.CharField(
        max_length=200, blank=True, help_text="Person or role who signed off."
    )
    acceptance_date = models.DateField(null=True, blank=True)
    acceptance_expiry_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)

    # Empty means active. Set when archived, cleared when restored (Step 6).
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        # Second line of defence: the database itself refuses values outside 1–5,
        # even if something bypasses the validation in `clean`.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(inherent_likelihood__gte=1, inherent_likelihood__lte=5),
                name="inherent_likelihood_1_to_5",
            ),
            models.CheckConstraint(
                condition=models.Q(inherent_impact__gte=1, inherent_impact__lte=5),
                name="inherent_impact_1_to_5",
            ),
            # Empty is allowed; any other value must still be on the 1–5 scale.
            models.CheckConstraint(
                condition=(
                    models.Q(residual_likelihood__isnull=True)
                    | models.Q(residual_likelihood__gte=1, residual_likelihood__lte=5)
                ),
                name="residual_likelihood_1_to_5_or_empty",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(residual_impact__isnull=True)
                    | models.Q(residual_impact__gte=1, residual_impact__lte=5)
                ),
                name="residual_impact_1_to_5_or_empty",
            ),
        ]

    def __str__(self):
        return f"{self.risk_id or 'New risk'}: {self.title}"

    @property
    def inherent_rating(self):
        """The rating label (Low/Medium/High/Critical) for the inherent score."""
        if self.inherent_score is None:
            return ""
        return rating_for_score(self.inherent_score)

    @property
    def residual_rating(self):
        """The rating label for the residual score, or blank if not assessed."""
        if not self.residual_score:
            return ""
        return rating_for_score(self.residual_score)

    @property
    def is_acceptance_expired(self):
        """
        True if the risk is accepted and the acceptance expiry date has passed.

        The acceptance is still valid on the expiry date itself; it counts as
        expired from the next day. Used to prompt a re-review.
        """
        return (
            self.response_type == self.ResponseType.ACCEPT
            and self.acceptance_expiry_date is not None
            and self.acceptance_expiry_date < timezone.localdate()
        )

    def clean(self):
        """
        Check the rules that involve more than one field.

        Input: the risk as filled in. Output: nothing if valid; otherwise a
        ValidationError listing each problem next to the field it concerns.
        Single-field rules (required fields, 1–5 scales) are checked by Django
        from the field definitions above.
        """
        errors = {}
        errors.update(self._check_response_rules())
        errors.update(self._check_acceptance_rules())
        errors.update(self._check_residual_rules())
        if errors:
            raise ValidationError(errors)

    def _check_response_rules(self):
        """Return errors for the response type and description rules."""
        errors = {}
        statuses_needing_response = (self.Status.IN_TREATMENT, self.Status.MONITORING)
        if self.status in statuses_needing_response and not self.response_type:
            errors["response_type"] = (
                "Choose a response type when the status is In treatment or Monitoring."
            )
        if self.response_type and not self.response_description.strip():
            errors["response_description"] = "Describe the chosen risk response."
        return errors

    def _check_acceptance_rules(self):
        """
        Return errors for the risk-acceptance fields.

        When the response is Accept, the approver and both dates are required
        and the expiry must be after the acceptance date. For any other
        response they must be empty, so no stale sign-off is left behind.
        """
        errors = {}
        if self.response_type == self.ResponseType.ACCEPT:
            if not self.accepted_by.strip():
                errors["accepted_by"] = "Record who accepted the risk."
            if not self.acceptance_date:
                errors["acceptance_date"] = "Record when the risk was accepted."
            if not self.acceptance_expiry_date:
                errors["acceptance_expiry_date"] = "Record when the acceptance expires."
            if (
                self.acceptance_date
                and self.acceptance_expiry_date
                and self.acceptance_expiry_date <= self.acceptance_date
            ):
                errors["acceptance_expiry_date"] = (
                    "The expiry date must be after the acceptance date."
                )
        else:
            message = "Only fill this in when the response type is Accept."
            if self.accepted_by.strip():
                errors["accepted_by"] = message
            if self.acceptance_date:
                errors["acceptance_date"] = message
            if self.acceptance_expiry_date:
                errors["acceptance_expiry_date"] = message
        return errors

    def _check_residual_rules(self):
        """
        Return errors for the residual scores.

        Both may be empty (not assessed yet). If one is filled in, the other
        is required, so a residual score is never calculated from half a pair.
        """
        errors = {}
        has_likelihood = self.residual_likelihood is not None
        has_impact = self.residual_impact is not None
        if has_likelihood and not has_impact:
            errors["residual_impact"] = "Record the residual impact as well as the likelihood."
        if has_impact and not has_likelihood:
            errors["residual_likelihood"] = "Record the residual likelihood as well as the impact."
        return errors

    def save(self, *args, **kwargs):
        """
        Save the risk, recalculating its score and assigning a Risk ID.

        The inherent score, and the residual score when both residual values
        are present, are recalculated on every save, so they can never drift
        out of sync with likelihood and impact. Residual uses the same
        multiplication and the same rating bands as inherent risk.

        The Risk ID is based on the database's record number, which SQLite
        never hands out twice, so an ID is never reused. That number only
        exists after the first save, so a new risk is saved, then given its
        ID. Both happen in one transaction: either both succeed or neither.
        """
        self.inherent_score = calculate_inherent_score(
            self.inherent_likelihood, self.inherent_impact
        )
        if self.residual_likelihood and self.residual_impact:
            self.residual_score = calculate_inherent_score(
                self.residual_likelihood, self.residual_impact
            )
        else:
            self.residual_score = None
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.risk_id:
                self.risk_id = f"RISK-{self.pk:04d}"
                super().save(update_fields=["risk_id"])


class RiskChange(models.Model):
    """
    One row of a risk's change history (audit trail).

    Each changed field gets its own row, e.g. "Inherent likelihood:
    3 – Possible → 4 – Likely". Events (Created, and later Archived/Restored)
    are stored with the event name in `field_name`. Rows are written only by
    risks/history.py and are never edited or deleted.
    """

    # PROTECT: a risk or user with history cannot be deleted, so the audit
    # trail can't lose its context. Deactivate users instead of deleting them.
    risk = models.ForeignKey(Risk, on_delete=models.PROTECT, related_name="changes")
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first; the record number breaks ties within the same save.
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.risk.risk_id} {self.field_name}: {self.old_value} → {self.new_value}"

    def save(self, *args, **kwargs):
        """Save a new history row. Refuses to change an existing one."""
        if self.pk is not None:
            raise ValueError("History rows cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete a history row."""
        raise ValueError("History rows cannot be deleted.")
