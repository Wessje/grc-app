"""
The input form for creating and editing an assessment.

The validation rules live on the Assessment model. Django runs them when
the form is checked, so this page and the admin screen accept the same data.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory

from assessments.effects import open_risk_for
from assessments.models import Assessment
from controls.models import Control
from processes.models import Process, ProcessControl
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


def _as_date(value):
    """Return a date. A string in YYYY-MM-DD is converted; anything else empty becomes None."""
    from datetime import date

    from django.utils.dateparse import parse_date

    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return parse_date(value)
    return None


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
        fields = [
            "process", "title", "review_date", "reviewer", "status",
            "next_review_date", "notes",
        ]
        widgets = {
            "review_date": DatePickerInput(),
            "next_review_date": DatePickerInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        """
        Offer active processes and solutions, and keep the current one.

        An archived process is not offered for a new review. If this review
        already points at one, that choice stays so it is not dropped.
        """
        super().__init__(*args, **kwargs)
        available = Q(archived_at__isnull=True)
        if self.instance.process_id:
            available |= Q(pk=self.instance.process_id)
        self.fields["process"].queryset = Process.objects.filter(available).order_by("name")
        self.fields["process"].required = True
        self.fields["process"].empty_label = "— Select —"
        self.fields["process"].label = "Process or solution"
        self.fields["process"].help_text = (
            "Choose one, then show its controls and risks. "
            "You can change it; show the list again before saving."
        )


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


class RiskRegisterLineForm(forms.Form):
    """
    The risk-register fields, plus the finding and evidence for this review.

    The same fields appear when you register a risk. They are checked against
    the risk's own rules when this line is included and the review is Complete.
    """

    findings = forms.CharField(
        required=False, label="Finding", widget=forms.Textarea(attrs={"rows": 3})
    )
    evidence = forms.CharField(
        required=False, label="Evidence", widget=forms.Textarea(attrs={"rows": 3})
    )
    title = forms.CharField(max_length=200, required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    category = forms.ModelChoiceField(
        queryset=RiskCategory.objects.all(), required=False, empty_label="— Select —"
    )
    owner = forms.CharField(max_length=200, required=False)
    risk_source = forms.CharField(max_length=200, required=False, label="Risk source")
    date_identified = forms.DateField(required=False, widget=DatePickerInput())
    inherent_likelihood = _score_field(LIKELIHOOD_CHOICES)
    inherent_impact = _score_field(IMPACT_CHOICES)
    residual_likelihood = _score_field(LIKELIHOOD_CHOICES)
    residual_impact = _score_field(IMPACT_CHOICES)
    status = forms.ChoiceField(
        choices=[("", "— Select —")] + list(Risk.Status.choices), required=False
    )
    response_type = forms.ChoiceField(
        label="Risk response type",
        choices=[("", "— Select —")] + list(Risk.ResponseType.choices),
        required=False,
    )
    response_description = forms.CharField(
        label="Risk response description",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    accepted_by = forms.CharField(max_length=200, required=False)
    acceptance_date = forms.DateField(required=False, widget=DatePickerInput())
    acceptance_expiry_date = forms.DateField(required=False, widget=DatePickerInput())
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, process=None, assessment_status=None, review_date=None, **kwargs):
        """
        Remember the process and whether the review is being saved as Complete.

        Inputs: the process or solution, the status being saved, and the
        review date (used when a new risk has no date of its own).
        """
        self.process = process
        self.assessment_status = assessment_status or Assessment.Status.PLANNED
        self.review_date = _as_date(review_date)
        super().__init__(*args, **kwargs)
        self.fields["inherent_likelihood"].label = "Inherent likelihood"
        self.fields["inherent_impact"].label = "Inherent impact"
        self.fields["residual_likelihood"].label = "Residual likelihood"
        self.fields["residual_impact"].label = "Residual impact"
        self.fields["risk_source"].help_text = (
            "Where the risk shows up in more detail, e.g. a system or a team."
        )

    def _check_register(self, cleaned, risk):
        """
        Check the register fields by the same rules as registering a risk.

        Inputs: the cleaned line, and a risk to check (not saved here).
        Output: nothing. Problems are attached to this line's fields.
        """
        if not (cleaned.get("findings") or "").strip():
            self.add_error("findings", "Record the finding when this risk is included.")
        if not (cleaned.get("evidence") or "").strip():
            self.add_error("evidence", "Describe the evidence when this risk is included.")
        if not cleaned.get("status"):
            cleaned["status"] = Risk.Status.OPEN
        if not cleaned.get("date_identified"):
            cleaned["date_identified"] = self.review_date
        risk.process = self.process
        risk.title = cleaned.get("title") or ""
        risk.description = cleaned.get("description") or ""
        risk.category = cleaned.get("category")
        risk.owner = cleaned.get("owner") or ""
        risk.risk_source = cleaned.get("risk_source") or ""
        risk.date_identified = cleaned.get("date_identified")
        risk.inherent_likelihood = cleaned.get("inherent_likelihood")
        risk.inherent_impact = cleaned.get("inherent_impact")
        risk.residual_likelihood = cleaned.get("residual_likelihood")
        risk.residual_impact = cleaned.get("residual_impact")
        risk.status = cleaned.get("status") or ""
        risk.response_type = cleaned.get("response_type") or ""
        risk.response_description = cleaned.get("response_description") or ""
        risk.accepted_by = cleaned.get("accepted_by") or ""
        risk.acceptance_date = cleaned.get("acceptance_date")
        risk.acceptance_expiry_date = cleaned.get("acceptance_expiry_date")
        risk.notes = cleaned.get("notes") or ""
        try:
            risk.full_clean()
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                if field in self.fields:
                    self.add_error(field, messages)
                else:
                    self.add_error(None, messages)


class RiskLineForm(RiskRegisterLineForm):
    """One current risk on a process or solution review."""

    risk_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    include = forms.BooleanField(required=False, label="Assess this risk")

    def __init__(self, *args, **kwargs):
        """Put the tick and the hidden id before the register fields."""
        super().__init__(*args, **kwargs)
        ordered = {}
        for name in ("risk_id", "include"):
            ordered[name] = self.fields.pop(name)
        ordered.update(self.fields)
        self.fields = ordered

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
        cleaned["include"] = bool(cleaned.get("include"))
        if not cleaned["include"] or self.assessment_status != Assessment.Status.COMPLETE:
            return cleaned
        self._check_register(cleaned, risk)
        return cleaned


class NewRiskForm(RiskRegisterLineForm):
    """A blank block for adding a risk from the review. An empty block is ignored."""

    def clean(self):
        """Ignore a block that was left empty. Check a filled one when the review is Complete."""
        cleaned = super().clean()
        cleaned["include"] = not _register_row_is_blank(cleaned)
        cleaned["risk"] = None
        if not cleaned["include"] or self.assessment_status != Assessment.Status.COMPLETE:
            return cleaned
        self._check_register(cleaned, Risk())
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
NewRiskFormSet = formset_factory(
    NewRiskForm, formset=BaseReviewLineFormSet, extra=1
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
    if assessment is not None and assessment.pk and assessment.process_id == process.pk:
        saved = {
            line.risk_id: line
            for line in assessment.risk_reviews.select_related("risk", "category")
            if line.risk_id
        }
    risks = list(
        process.risks.filter(archived_at__isnull=True)
        .exclude(status=Risk.Status.CLOSED)
        .order_by("risk_id")
    )
    for line in saved.values():
        if line.risk not in risks:
            risks.append(line.risk)
    return [_risk_row(risk, saved.get(risk.pk)) for risk in risks]


def new_risk_initial(process, assessment=None):
    """
    Build the starting rows for risks added from this review and not yet on the register.

    Inputs: the process being shown, and the assessment when one is being edited.
    Output: one dictionary per saved draft. Drafts are hidden when the process
    on the form is not the one they were saved for.
    """
    if assessment is None or not assessment.pk or assessment.process_id != process.pk:
        return []
    drafts = assessment.risk_reviews.filter(risk__isnull=True).order_by("id")
    return [_register_from_line(line) for line in drafts]


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
    """
    Return one risk form row.

    A saved line that already has a title keeps that draft. Otherwise the
    row shows the risk as it stands on the register, so the fields match
    the risk page. The tick starts unticked.
    """
    if line is not None and line.title:
        row = _register_from_line(line)
    else:
        row = _register_from_risk(risk)
        if line is not None and line.close_risk:
            row["status"] = Risk.Status.CLOSED
    row["risk_id"] = risk.pk
    row["include"] = line.include if line is not None else False
    row["findings"] = line.findings if line is not None else ""
    row["evidence"] = line.evidence if line is not None else ""
    return row


def _register_from_risk(risk):
    """Return the register fields copied from a risk, for the assessment form."""
    return {
        "title": risk.title,
        "description": risk.description,
        "category": risk.category_id,
        "owner": risk.owner,
        "risk_source": risk.risk_source,
        "date_identified": risk.date_identified,
        "inherent_likelihood": risk.inherent_likelihood,
        "inherent_impact": risk.inherent_impact,
        "residual_likelihood": risk.residual_likelihood or "",
        "residual_impact": risk.residual_impact or "",
        "status": risk.status,
        "response_type": risk.response_type,
        "response_description": risk.response_description,
        "accepted_by": risk.accepted_by,
        "acceptance_date": risk.acceptance_date,
        "acceptance_expiry_date": risk.acceptance_expiry_date,
        "notes": risk.notes,
    }


def _register_from_line(line):
    """Return the register fields copied from a saved assessment line."""
    return {
        "title": line.title,
        "description": line.description,
        "category": line.category_id,
        "owner": line.owner,
        "risk_source": line.risk_source,
        "date_identified": line.date_identified,
        "inherent_likelihood": line.likelihood or "",
        "inherent_impact": line.impact or "",
        "residual_likelihood": line.residual_likelihood or "",
        "residual_impact": line.residual_impact or "",
        "status": line.risk_status,
        "response_type": line.response_type,
        "response_description": line.response_description,
        "accepted_by": line.accepted_by,
        "acceptance_date": line.acceptance_date,
        "acceptance_expiry_date": line.acceptance_expiry_date,
        "notes": line.notes,
        "findings": line.findings,
        "evidence": line.evidence,
        "include": line.include,
    }


def _register_row_is_blank(cleaned):
    """
    True when a new-risk block was left empty.

    Input: the cleaned fields. Output: True if there is nothing to save.
    Status left on "Select" and empty scores count as empty.
    """
    text_fields = (
        "title", "description", "owner", "risk_source", "response_type",
        "response_description", "accepted_by", "notes", "findings", "evidence",
    )
    if any((cleaned.get(name) or "").strip() for name in text_fields):
        return False
    if cleaned.get("category") or cleaned.get("date_identified"):
        return False
    if cleaned.get("acceptance_date") or cleaned.get("acceptance_expiry_date"):
        return False
    if cleaned.get("status"):
        return False
    score_fields = (
        "inherent_likelihood", "inherent_impact",
        "residual_likelihood", "residual_impact",
    )
    return not any(cleaned.get(name) is not None for name in score_fields)

