"""
The input form for creating and editing a risk.

The validation rules themselves live in the Risk model (risks/models.py);
this form only decides which fields appear, in which groups, and with which
input boxes. Django runs the model's rules automatically when the form is
checked, so the form and the admin screen enforce the same rules.
"""

from django import forms
from django.db.models import Q

from processes.models import Process
from risks.models import Risk


class DatePickerInput(forms.DateInput):
    """A date box that shows the browser's calendar picker."""

    input_type = "date"

    def __init__(self, **kwargs):
        # The browser's date picker always sends and expects YYYY-MM-DD.
        super().__init__(format="%Y-%m-%d", **kwargs)


class RiskForm(forms.ModelForm):
    """Form with every field a person may fill in for a risk."""

    # Sections shown on the page: (heading, field names).
    FIELD_GROUPS = [
        ("Risk", ["title", "description", "category", "process", "owner",
                  "risk_source", "date_identified"]),
        ("Inherent risk", ["inherent_likelihood", "inherent_impact"]),
        ("Residual risk (after controls)", ["residual_likelihood", "residual_impact"]),
        ("Treatment", ["status", "response_type", "response_description"]),
        ("Risk acceptance (only when the response type is Accept)",
         ["accepted_by", "acceptance_date", "acceptance_expiry_date"]),
        ("Other", ["notes"]),
    ]

    class Meta:
        model = Risk
        fields = [
            "title", "description", "category", "process", "owner", "risk_source",
            "date_identified", "inherent_likelihood", "inherent_impact",
            "residual_likelihood", "residual_impact",
            "status", "response_type", "response_description",
            "accepted_by", "acceptance_date", "acceptance_expiry_date", "notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "response_description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "date_identified": DatePickerInput(),
            "acceptance_date": DatePickerInput(),
            "acceptance_expiry_date": DatePickerInput(),
        }

    def __init__(self, *args, **kwargs):
        """
        Limit the process list to ones that are still in use.

        An archived process or solution is not offered for a new link. If this
        risk already points at one that was archived later, that choice stays
        in the list so the link is not dropped by accident.
        """
        super().__init__(*args, **kwargs)
        available = Q(archived_at__isnull=True)
        if self.instance.process_id:
            available |= Q(pk=self.instance.process_id)
        self.fields["process"].queryset = Process.objects.filter(available).order_by("name")

    def grouped_fields(self):
        """
        Return the form's fields arranged in their page sections.

        Output: a list of (heading, [form fields]) used by the template.
        """
        return [
            (heading, [self[name] for name in field_names])
            for heading, field_names in self.FIELD_GROUPS
        ]
