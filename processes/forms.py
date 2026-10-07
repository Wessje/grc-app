"""
The input form for creating and editing a process or a solution.

The fields match the record. Django checks the model's rules when the form
is submitted, so this page and the admin screen accept the same data.
"""

from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from controls.models import Control
from processes.models import Process, ProcessControl


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


class ProcessControlLinkForm(forms.ModelForm):
    """One control in scope for the process or solution."""

    class Meta:
        model = ProcessControl
        fields = ["control"]

    def __init__(self, *args, **kwargs):
        """
        Offer active controls, and keep a control that was archived later.

        A spare row may be left blank. A new row can only pick an active
        control. A row that already points at an archived control keeps that
        choice, so editing the process does not drop the link.
        """
        super().__init__(*args, **kwargs)
        self.fields["control"].required = False
        allowed = Q(archived_at__isnull=True)
        if self.instance.pk and self.instance.control_id:
            allowed = allowed | Q(pk=self.instance.control_id)
        self.fields["control"].queryset = Control.objects.filter(allowed)


ProcessControlLinkFormSet = inlineformset_factory(
    Process,
    ProcessControl,
    form=ProcessControlLinkForm,
    extra=1,
    can_delete=True,
)
