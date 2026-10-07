"""
The input form for creating and editing an assessment.

The validation rules live on the Assessment model. Django runs them when
the form is checked, so this page and the admin screen accept the same data.
"""

from django import forms
from django.db.models import Q

from assessments.models import Assessment
from controls.models import Control
from risks.models import Risk


class DatePickerInput(forms.DateInput):
    """A date box that shows the browser's calendar picker."""

    input_type = "date"

    def __init__(self, **kwargs):
        # The browser's date picker always sends and expects YYYY-MM-DD.
        super().__init__(format="%Y-%m-%d", **kwargs)


class AssessmentForm(forms.ModelForm):
    """Form with every field a person may fill in for an assessment."""

    # Sections shown on the page: (heading, field names).
    FIELD_GROUPS = [
        ("Review", ["title", "assessment_type", "review_date", "reviewer", "status"]),
        ("Subject", ["risk", "control"]),
        ("Result", ["outcome", "findings", "evidence", "next_review_date"]),
        ("Other", ["notes"]),
    ]

    class Meta:
        model = Assessment
        fields = [
            "title", "assessment_type", "review_date", "reviewer", "status",
            "risk", "control", "outcome", "findings", "evidence",
            "next_review_date", "notes",
        ]
        widgets = {
            "review_date": DatePickerInput(),
            "next_review_date": DatePickerInput(),
            "findings": forms.Textarea(attrs={"rows": 3}),
            "evidence": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A new assessment can only name an active risk or control. An
        # existing row keeps its current subject even if that record has
        # since been archived.
        risk_filter = Q(archived_at__isnull=True)
        control_filter = Q(archived_at__isnull=True)
        if self.instance.pk and self.instance.risk_id:
            risk_filter = risk_filter | Q(pk=self.instance.risk_id)
        if self.instance.pk and self.instance.control_id:
            control_filter = control_filter | Q(pk=self.instance.control_id)
        self.fields["risk"].queryset = Risk.objects.filter(risk_filter).order_by("risk_id")
        self.fields["control"].queryset = Control.objects.filter(control_filter).order_by("control_id")

    def grouped_fields(self):
        """
        Return the form's fields arranged in their page sections.

        Output: a list of (heading, [form fields]) used by the template.
        """
        return [
            (heading, [self[name] for name in field_names])
            for heading, field_names in self.FIELD_GROUPS
        ]
