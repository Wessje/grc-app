"""
The rows for linking controls to one risk, used on the risk form.

Each row is one control plus how effective it is for that risk. An empty
spare row is ignored. The same control cannot be linked twice.
"""

from django import forms
from django.forms import inlineformset_factory

from controls.models import RiskControl
from risks.models import Risk


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
