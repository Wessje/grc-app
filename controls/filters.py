"""
The framework filter on the control register.

The choice arrives in the web address (for example ?framework=iso_27001).
An unknown value is ignored, so the list falls back to every control.
"""

from django import forms

from controls.models import FrameworkRequirement


class ControlFilterForm(forms.Form):
    """Optional framework filter. Blank means every control."""

    framework = forms.ChoiceField(
        choices=[("", "Any framework")] + list(FrameworkRequirement.Framework.choices),
        required=False,
    )


def selected_framework(form):
    """
    Return the framework code from the filter, if it is one of the catalogues.

    Input: a filter form filled from the web address. Output: a framework
    code such as "iso_27001", or "" when the choice is missing or invalid.
    """
    if not form.is_valid():
        return ""
    return form.cleaned_data.get("framework", "")
