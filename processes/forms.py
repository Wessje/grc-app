"""
The input form for creating and editing a process or a solution.

The fields match the record. Django checks the model's rules when the form
is submitted, so this page and the admin screen accept the same data.
"""

from django import forms

from processes.models import Process


class ProcessForm(forms.ModelForm):
    """Form with every field a person may fill in for a process or solution."""

    # Sections shown on the page: (heading, field names).
    FIELD_GROUPS = [
        ("Process or solution", ["kind", "name", "description", "owner"]),
        ("Other", ["notes"]),
    ]

    class Meta:
        model = Process
        fields = ["kind", "name", "description", "owner", "notes"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def grouped_fields(self):
        """
        Return the form's fields arranged in their page sections.

        Output: a list of (heading, [form fields]) used by the template.
        """
        return [
            (heading, [self[name] for name in field_names])
            for heading, field_names in self.FIELD_GROUPS
        ]
