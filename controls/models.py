"""
The control register: one row per safeguard that reduces risk (for example
MFA or backups), the links from those controls to the risks they address,
and the links from controls to framework requirements.

This file is the central definition of a control, so the admin screen and
our own forms enforce the same rules.
"""

from django.db import models, transaction


class Control(models.Model):
    """One safeguard in the control register."""

    class ControlType(models.TextChoices):
        PREVENTIVE = "preventive", "Preventive"
        DETECTIVE = "detective", "Detective"
        CORRECTIVE = "corrective", "Corrective"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PLACE = "in_place", "In place"
        NOT_OPERATING = "not_operating", "Not operating"

    # Generated after the first save (see `save`); empty until then.
    control_id = models.CharField(
        "control ID", max_length=20, unique=True, null=True, blank=True, editable=False
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    owner = models.CharField(max_length=200, help_text="Person or role.")
    control_type = models.CharField("type", max_length=20, choices=ControlType)
    # Planned until someone confirms the control is actually operating.
    status = models.CharField(max_length=20, choices=Status, default=Status.PLANNED)
    notes = models.TextField(blank=True)

    # Empty means active. Set when archived, cleared when restored.
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.control_id or 'New control'}: {self.title}"

    def save(self, *args, **kwargs):
        """
        Save the control and assign a Control ID on the first save.

        The ID is based on the database's record number, which SQLite never
        hands out twice, so an ID is never reused. That number only exists
        after the first save, so a new control is saved, then given its ID.
        Both happen in one transaction: either both succeed or neither.
        """
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.control_id:
                self.control_id = f"CTRL-{self.pk:04d}"
                super().save(update_fields=["control_id"])


class RiskControl(models.Model):
    """
    One link: this control addresses this risk, with an effectiveness rating.

    The rating is about this pairing only. The same control can be effective
    for one risk and only partly effective for another. The link belongs to
    the controls module; the risk table itself is unchanged. A risk or control
    that still has a link cannot be deleted.
    """

    class Effectiveness(models.TextChoices):
        EFFECTIVE = "effective", "Effective"
        PARTIAL = "partial", "Partially effective"
        INEFFECTIVE = "ineffective", "Ineffective"

    risk = models.ForeignKey(
        "risks.Risk", on_delete=models.PROTECT, related_name="control_links"
    )
    control = models.ForeignKey(
        Control, on_delete=models.PROTECT, related_name="risk_links"
    )
    effectiveness = models.CharField(max_length=20, choices=Effectiveness)

    class Meta:
        ordering = ["control__control_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["risk", "control"], name="one_link_per_risk_and_control"
            ),
        ]

    def __str__(self):
        return f"{self.control} → {self.risk} ({self.get_effectiveness_display()})"


class FrameworkRequirement(models.Model):
    """
    One requirement from a framework catalogue.

    The catalogues are reference lists (ISO 27001, NIST CSF, SOC 2): a
    reference code and a short title we wrote, not the text of the standard.
    """

    class Framework(models.TextChoices):
        ISO_27001 = "iso_27001", "ISO 27001"
        NIST_CSF = "nist_csf", "NIST CSF"
        SOC_2 = "soc_2", "SOC 2"

    framework = models.CharField(max_length=20, choices=Framework)
    reference = models.CharField(
        max_length=30,
        help_text="The requirement's own identifier, for example A.5.15 or PR.AA-01.",
    )
    title = models.CharField(max_length=200)

    class Meta:
        ordering = ["framework", "reference"]
        verbose_name = "framework requirement"
        constraints = [
            # A.5.15 may exist in only one framework. The same code in another
            # framework is a different requirement.
            models.UniqueConstraint(
                fields=["framework", "reference"], name="one_reference_per_framework"
            ),
        ]

    def __str__(self):
        return f"{self.get_framework_display()} {self.reference}: {self.title}"


class ControlRequirement(models.Model):
    """
    One mapping: this control addresses this framework requirement.

    One control can map to several requirements, including from different
    frameworks. One requirement can be met by several controls. A control or
    requirement that still has a mapping cannot be deleted.
    """

    control = models.ForeignKey(
        Control, on_delete=models.PROTECT, related_name="requirement_links"
    )
    requirement = models.ForeignKey(
        FrameworkRequirement, on_delete=models.PROTECT, related_name="control_links"
    )

    class Meta:
        ordering = ["requirement__framework", "requirement__reference"]
        verbose_name = "framework mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["control", "requirement"],
                name="one_mapping_per_control_and_requirement",
            ),
        ]

    def __str__(self):
        return f"{self.control.control_id} → {self.requirement.reference}"
