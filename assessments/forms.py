"""
The input form for creating and editing an assessment.

The validation rules live on the Assessment model. Django runs them when
the form is checked, so this page and the admin screen accept the same data.
"""

from django import forms
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory

from assessments.effects import open_risk_for
from assessments.models import Assessment
from controls.models import Control
from processes.models import ProcessControl
from risks.models import IMPACT_CHOICES, LIKELIHOOD_CHOICES, Risk, RiskCategory


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
        # A process or solution review is started from that record's page,
        # where the control and risk lines are filled in.
        self.fields["assessment_type"].choices = [
            choice for choice in Assessment.AssessmentType.choices
            if choice[0] != Assessment.AssessmentType.PROCESS_REVIEW
        ]

    def grouped_fields(self):
        """
        Return the form's fields arranged in their page sections.

        Output: a list of (heading, [form fields]) used by the template.
        """
        return [
            (heading, [self[name] for name in field_names])
            for heading, field_names in self.FIELD_GROUPS
        ]


def _score_field(choices):
    """A likelihood or impact box. Empty is allowed; a choice is a number from 1 to 5."""
    return forms.TypedChoiceField(
        choices=[("", "— Select —")] + list(choices),
        coerce=int,
        required=False,
        empty_value=None,
    )


class ProcessReviewForm(forms.ModelForm):
    """The header of a process or solution review. The lines are separate forms."""

    class Meta:
        model = Assessment
        fields = ["title", "review_date", "reviewer", "status", "next_review_date", "notes"]
        widgets = {
            "review_date": DatePickerInput(),
            "next_review_date": DatePickerInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ControlLineForm(forms.Form):
    """One in-scope control on a process or solution review."""

    control_id = forms.IntegerField(widget=forms.HiddenInput)
    include = forms.BooleanField(required=False, label="Include in this assessment")
    outcome = forms.ChoiceField(
        choices=[("", "— Select —")] + list(Assessment.Outcome.choices),
        required=False,
    )
    findings = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    evidence = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    likelihood = _score_field(LIKELIHOOD_CHOICES)
    impact = _score_field(IMPACT_CHOICES)
    category = forms.ModelChoiceField(
        queryset=RiskCategory.objects.all(), required=False, empty_label="— Select —"
    )

    def __init__(self, *args, process=None, assessment=None, assessment_status=None, **kwargs):
        """
        Remember the process and whether the review is being saved as Complete.

        Those are not fields on the line. The view passes them in so this
        line can check its own rules.
        """
        self.process = process
        self.assessment = assessment
        self.assessment_status = assessment_status or Assessment.Status.PLANNED
        super().__init__(*args, **kwargs)

    def clean(self):
        """Check this control line. An unticked line is stored but not applied."""
        cleaned = super().clean()
        control = self._control_in_scope(cleaned.get("control_id"))
        if control is None:
            self.add_error("control_id", "Choose a control that is in scope for this process or solution.")
            return cleaned
        cleaned["control"] = control
        if not cleaned.get("include"):
            return cleaned
        if self.assessment_status != Assessment.Status.COMPLETE:
            return cleaned
        self._check_complete(cleaned, control)
        return cleaned

    def _control_in_scope(self, control_id):
        """Return the control when it is in scope for this process, otherwise None."""
        if not control_id or self.process is None:
            return None
        link = (
            ProcessControl.objects.filter(process=self.process, control_id=control_id)
            .select_related("control")
            .first()
        )
        return link.control if link else None

    def _check_complete(self, cleaned, control):
        """Require a full result, and scores only when the control did not pass."""
        outcome = cleaned.get("outcome")
        if not outcome:
            self.add_error("outcome", "Record the outcome when this control is included.")
        if not (cleaned.get("findings") or "").strip():
            self.add_error("findings", "Record the finding when this control is included.")
        if not (cleaned.get("evidence") or "").strip():
            self.add_error("evidence", "Describe the evidence when this control is included.")
        failed = outcome in (Assessment.Outcome.PARTIAL, Assessment.Outcome.UNSATISFACTORY)
        if outcome == Assessment.Outcome.SATISFACTORY and (
            cleaned.get("likelihood") or cleaned.get("impact") or cleaned.get("category")
        ):
            self.add_error(
                "likelihood",
                "Leave the scores empty when the outcome is Satisfactory. "
                "A satisfactory test does not create or close a risk.",
            )
        if failed and (cleaned.get("likelihood") is None or cleaned.get("impact") is None):
            self.add_error(
                "likelihood",
                "Record likelihood and impact. A risk cannot be saved without both.",
            )
        if failed and cleaned.get("category") is None and not self._already_has_risk(control):
            self.add_error(
                "category",
                "Choose a category. A new risk cannot be saved without one.",
            )

    def _already_has_risk(self, control):
        """True when this line, or the process, already has a risk for this control."""
        if self.assessment is not None and self.assessment.pk:
            existing_line = self.assessment.control_results.filter(control=control).first()
            if existing_line is not None and existing_line.risk_id:
                return True
        return open_risk_for(self.process, control) is not None


class RiskLineForm(forms.Form):
    """One current risk on a process or solution review."""

    risk_id = forms.IntegerField(widget=forms.HiddenInput)
    include = forms.BooleanField(required=False, label="Reassess this risk")
    findings = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    evidence = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    likelihood = _score_field(LIKELIHOOD_CHOICES)
    impact = _score_field(IMPACT_CHOICES)
    close_risk = forms.BooleanField(required=False, label="Close this risk")

    def __init__(self, *args, process=None, assessment_status=None, **kwargs):
        """Remember the process and the status being saved. See ControlLineForm."""
        self.process = process
        self.assessment_status = assessment_status or Assessment.Status.PLANNED
        super().__init__(*args, **kwargs)

    def clean(self):
        """Check this risk line. An unticked line does not change the risk."""
        cleaned = super().clean()
        risk = Risk.objects.filter(
            pk=cleaned.get("risk_id") or 0,
            process=self.process,
            archived_at__isnull=True,
        ).first()
        if risk is None:
            self.add_error("risk_id", "Choose a risk that belongs to this process or solution.")
            return cleaned
        cleaned["risk"] = risk
        if not cleaned.get("include"):
            if cleaned.get("close_risk"):
                self.add_error("close_risk", "Tick Reassess this risk before closing it.")
            return cleaned
        if self.assessment_status != Assessment.Status.COMPLETE:
            return cleaned
        if not (cleaned.get("findings") or "").strip():
            self.add_error("findings", "Record the finding when this risk is reassessed.")
        if not (cleaned.get("evidence") or "").strip():
            self.add_error("evidence", "Describe the evidence when this risk is reassessed.")
        has_likelihood = cleaned.get("likelihood") is not None
        has_impact = cleaned.get("impact") is not None
        if has_likelihood != has_impact:
            self.add_error("likelihood", "Record both likelihood and impact, or leave both empty.")
        return cleaned


class BaseReviewLineFormSet(BaseFormSet):
    """Shared checks for the control lines and the risk lines."""

    def clean(self):
        """Count how many lines were ticked. The view asks for at least one."""
        self.included_count = sum(
            1 for form in self.forms
            if form.cleaned_data and form.cleaned_data.get("include")
        )


ControlLineFormSet = formset_factory(
    ControlLineForm, formset=BaseReviewLineFormSet, extra=0
)
RiskLineFormSet = formset_factory(
    RiskLineForm, formset=BaseReviewLineFormSet, extra=0
)


def control_line_initial(process, assessment=None):
    """
    Build the starting rows for the controls in scope.

    Inputs: the process, and the assessment when one is being edited.
    Output: a list of dictionaries, one per in-scope control. A saved line
    fills in what was entered last time.
    """
    saved = {}
    if assessment is not None and assessment.pk:
        saved = {line.control_id: line for line in assessment.control_results.all()}
    rows = []
    links = process.control_links.select_related("control").order_by("control__control_id")
    for link in links:
        line = saved.get(link.control_id)
        rows.append(_control_row(link.control, line))
    return rows


def risk_line_initial(process, assessment=None):
    """
    Build the starting rows for the risks on this process.

    Current risks are those that are not archived and not Closed. A risk
    this review already reassessed stays on the form even if it is now
    Closed, so the close can be seen and edited.
    """
    saved = {}
    if assessment is not None and assessment.pk:
        saved = {line.risk_id: line for line in assessment.risk_reviews.select_related("risk")}
    risks = list(
        process.risks.filter(archived_at__isnull=True)
        .exclude(status=Risk.Status.CLOSED)
        .order_by("risk_id")
    )
    for line in saved.values():
        if line.risk not in risks:
            risks.append(line.risk)
    return [_risk_row(risk, saved.get(risk.pk)) for risk in risks]


def _control_row(control, line):
    """Return one control form row, filled from a saved line when there is one."""
    if line is None:
        return {"control_id": control.pk, "include": True}
    return {
        "control_id": control.pk,
        "include": line.include,
        "outcome": line.outcome,
        "findings": line.findings,
        "evidence": line.evidence,
        "likelihood": line.likelihood or "",
        "impact": line.impact or "",
        "category": line.category_id,
    }


def _risk_row(risk, line):
    """Return one risk form row, filled from a saved line when there is one."""
    if line is None:
        return {"risk_id": risk.pk, "include": False}
    return {
        "risk_id": risk.pk,
        "include": line.include,
        "findings": line.findings,
        "evidence": line.evidence,
        "likelihood": line.likelihood or "",
        "impact": line.impact or "",
        "close_risk": line.close_risk,
    }

