"""
Processes and solutions: the things a risk belongs to.

One list covers both. A business process (for example payroll) and a
solution you run (for example email) are the same kind of record, told
apart by the type. Every risk points at one of these. A control test
will later be done in the context of one of them.

This file is the central definition, so the admin screen and our own forms
enforce the same rules.
"""

from django.db import models, transaction


class Process(models.Model):
    """One business process or one solution."""

    class Kind(models.TextChoices):
        PROCESS = "process", "Process"
        SOLUTION = "solution", "Solution"

    # Generated after the first save (see `save`); empty until then.
    process_id = models.CharField(
        "ID", max_length=20, unique=True, null=True, blank=True, editable=False
    )
    kind = models.CharField("type", max_length=20, choices=Kind)
    name = models.CharField(max_length=200)
    description = models.TextField()
    owner = models.CharField(max_length=200, help_text="Person or role.")
    notes = models.TextField(blank=True)

    # Empty means active. Set when archived, cleared when restored.
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.process_id or 'New'}: {self.name}"

    def save(self, *args, **kwargs):
        """
        Save the record and assign an ID on the first save.

        The ID is based on the database's record number, which SQLite never
        hands out twice, so an ID is never reused. That number only exists
        after the first save, so a new record is saved, then given its ID.
        Both happen in one transaction: either both succeed or neither.
        Processes and solutions share one sequence (PROC-0001, PROC-0002, …).
        """
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.process_id:
                self.process_id = f"PROC-{self.pk:04d}"
                super().save(update_fields=["process_id"])
