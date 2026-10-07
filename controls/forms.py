"""
Forms for the control register.

ControlForm is the page for creating and editing a control. The link formset
is the set of rows on the risk form: each row is one control plus how
effective it is for that risk. An empty spare row is ignored. The same
control cannot be linked twice.
"""

from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from controls.models import Control, RiskControl
from risks.models import Risk


class ControlForm(forms.ModelForm):
    """Form with every field a person may fill in for a control."""

    # Sections shown on the page: (heading, field names).
    FIELD_GROUPS = [
        ("Control", ["title", "description", "owner", "control_type", "status"]),
        ("Other", ["notes"]),
    ]

    class Meta:
        model = Control
        fields = ["title", "description", "owner", "control_type", "status", "notes"]
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


class RiskControlLinkForm(forms.ModelForm):
    """One control linked to the risk, with its effectiveness."""

    class Meta:
        model = RiskControl
        fields = ["control", "effectiveness"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A spare row may be left blank. A row with a control still needs an
        # effectiveness; that is checked in `clean`.
        self.fields["control"].required = False
        self.fields["effectiveness"].required = False
        # A new row can only pick an active control. A row that already
        # points at an archived control keeps that choice, so editing the
        # risk does not drop the link.
        allowed = Q(archived_at__isnull=True)
        if self.instance.pk and self.instance.control_id:
            allowed = allowed | Q(pk=self.instance.control_id)
        self.fields["control"].queryset = Control.objects.filter(allowed)

    def clean(self):
        """Require both fields once either of them is filled in."""
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        control = cleaned.get("control")
        effectiveness = cleaned.get("effectiveness")
        if control and not effectiveness:
            self.add_error(
                "effectiveness",
                "Record how effective this control is for this risk.",
            )
        if effectiveness and not control:
            self.add_error("control", "Choose the control this effectiveness applies to.")
        return cleaned


RiskControlLinkFormSet = inlineformset_factory(
    Risk,
    RiskControl,
    form=RiskControlLinkForm,
    extra=1,
    can_delete=True,
)
