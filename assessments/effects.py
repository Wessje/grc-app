"""
Applies a completed process or solution review to the risk register.

A control that is unsatisfactory or only partly satisfactory creates an
open risk, or updates the open risk already linked to that process and
that control. A satisfactory result does not create a risk and does not
close one. A risk included in the review is updated from the same fields
used on the risk register. It is closed only when that line's status is
Closed. A new risk line creates a risk on this process or solution.
"""

from django.db import transaction

from assessments.models import AssessedControl, AssessedRisk, Assessment
from controls.links import record_control_link_changes, snapshot_control_links
from controls.models import RiskControl
from risks.history import save_risk_with_history
from risks.models import Risk


def open_risk_for(process, control):
    """
    Return the open risk for this process and control, if there is one.

    Input: a process or solution, and a control. Output: the newest risk
    that belongs to that process, is linked to that control, is not
    archived and is not Closed. Output is None when there is no such risk.
    "Open" here means still active: Open, In treatment or Monitoring.
    """
    return (
        Risk.objects.filter(
            process=process,
            archived_at__isnull=True,
            control_links__control=control,
        )
        .exclude(status=Risk.Status.CLOSED)
        .order_by("-id")
        .first()
    )


def save_review_lines(assessment, control_rows, risk_rows, new_risk_rows):
    """
    Store the control and risk lines for a process or solution review.

    Inputs: the saved assessment, and the cleaned rows from the three forms
    (controls, current risks, and new risks). Output: nothing. A row left
    unticked is stored too, so the next edit shows that choice. The risk a
    control line already created is kept. An empty new-risk block is not stored.
    """
    seen_controls = []
    for row in control_rows:
        line, _created = AssessedControl.objects.get_or_create(
            assessment=assessment, control=row["control"]
        )
        line.include = bool(row.get("include"))
        line.outcome = row.get("outcome") or ""
        line.findings = row.get("findings") or ""
        line.evidence = row.get("evidence") or ""
        line.likelihood = row.get("likelihood")
        line.impact = row.get("impact")
        line.category = row.get("category")
        line.save()
        seen_controls.append(line.pk)
    assessment.control_results.exclude(pk__in=seen_controls).delete()

    seen_risks = []
    for row in risk_rows:
        line, _created = AssessedRisk.objects.get_or_create(
            assessment=assessment, risk=row["risk"]
        )
        _fill_risk_line(line, row)
        line.save()
        seen_risks.append(line.pk)
    # Drafts have no risk yet, so they are replaced from the new-risk blocks.
    assessment.risk_reviews.filter(risk__isnull=True).delete()
    for row in new_risk_rows:
        if not row.get("include"):
            continue
        line = AssessedRisk(assessment=assessment, risk=None)
        _fill_risk_line(line, row)
        line.save()
        seen_risks.append(line.pk)
    assessment.risk_reviews.exclude(pk__in=seen_risks).delete()


def apply_completed_review(assessment, user):
    """
    Create, update or close risks for a review that is Complete.

    Inputs: the saved assessment and the logged-in user. Output: nothing.
    Does nothing unless this is a completed process or solution review.
    The register changes and the lines that remember them are saved
    together: either all of them succeed or none do.
    """
    if assessment.assessment_type != Assessment.AssessmentType.PROCESS_REVIEW:
        return
    if assessment.status != Assessment.Status.COMPLETE:
        return
    with transaction.atomic():
        for line in assessment.control_results.select_related("control", "category", "risk"):
            _apply_control_line(assessment, line, user)
        for line in assessment.risk_reviews.select_related("risk", "category"):
            _apply_risk_line(assessment, line, user)


def _apply_control_line(assessment, line, user):
    """Create or update a risk when this control did not pass. Otherwise do nothing."""
    if not line.include:
        return
    if line.outcome == Assessment.Outcome.SATISFACTORY:
        return
    if line.outcome not in (Assessment.Outcome.PARTIAL, Assessment.Outcome.UNSATISFACTORY):
        return

    risk = line.risk or open_risk_for(assessment.process, line.control)
    if risk is None:
        risk = Risk(
            title=_risk_title(line.control, assessment.process),
            description=line.findings,
            category=line.category,
            process=assessment.process,
            owner=assessment.process.owner,
            risk_source=line.control.title[:200],
            date_identified=assessment.review_date,
            inherent_likelihood=line.likelihood,
            inherent_impact=line.impact,
            status=Risk.Status.OPEN,
        )
        risk.full_clean()
        save_risk_with_history(risk, user)
    else:
        risk.description = line.findings
        risk.inherent_likelihood = line.likelihood
        risk.inherent_impact = line.impact
        risk.full_clean()
        save_risk_with_history(risk, user)

    effectiveness = (
        RiskControl.Effectiveness.PARTIAL
        if line.outcome == Assessment.Outcome.PARTIAL
        else RiskControl.Effectiveness.INEFFECTIVE
    )
    _link_control(risk, line.control, effectiveness, user)
    if line.risk_id != risk.pk:
        line.risk = risk
        line.save(update_fields=["risk"])


def _apply_risk_line(assessment, line, user):
    """
    Update a current risk, or create one, from the register fields on the line.

    The risk stays on this process or solution. It is closed only when the
    line's status is Closed. The finding stays on the line; the risk's
    description is whatever was entered in the description field.
    """
    if not line.include:
        return
    risk = line.risk or Risk(process=assessment.process)
    risk.process = assessment.process
    risk.title = line.title
    risk.description = line.description
    risk.category = line.category
    risk.owner = line.owner
    risk.risk_source = line.risk_source
    risk.date_identified = line.date_identified
    risk.inherent_likelihood = line.likelihood
    risk.inherent_impact = line.impact
    risk.residual_likelihood = line.residual_likelihood
    risk.residual_impact = line.residual_impact
    risk.status = line.risk_status or Risk.Status.OPEN
    risk.response_type = line.response_type
    risk.response_description = line.response_description
    risk.accepted_by = line.accepted_by
    risk.acceptance_date = line.acceptance_date
    risk.acceptance_expiry_date = line.acceptance_expiry_date
    risk.notes = line.notes
    risk.full_clean()
    save_risk_with_history(risk, user)
    if line.risk_id != risk.pk:
        line.risk = risk
        line.save(update_fields=["risk"])


def _fill_risk_line(line, row):
    """
    Copy one form row onto an assessment risk line.

    Inputs: the line to fill, and the cleaned form row. Output: nothing.
    Likelihood and impact store the inherent scores. close_risk is set
    when the status is Closed and the line is included.
    """
    line.include = bool(row.get("include"))
    line.findings = row.get("findings") or ""
    line.evidence = row.get("evidence") or ""
    line.title = row.get("title") or ""
    line.description = row.get("description") or ""
    line.category = row.get("category")
    line.owner = row.get("owner") or ""
    line.risk_source = row.get("risk_source") or ""
    line.date_identified = row.get("date_identified")
    line.likelihood = row.get("inherent_likelihood")
    line.impact = row.get("inherent_impact")
    line.residual_likelihood = row.get("residual_likelihood")
    line.residual_impact = row.get("residual_impact")
    line.risk_status = row.get("status") or ""
    line.response_type = row.get("response_type") or ""
    line.response_description = row.get("response_description") or ""
    line.accepted_by = row.get("accepted_by") or ""
    line.acceptance_date = row.get("acceptance_date")
    line.acceptance_expiry_date = row.get("acceptance_expiry_date")
    line.notes = row.get("notes") or ""
    line.close_risk = line.include and line.risk_status == Risk.Status.CLOSED


def _risk_title(control, process):
    """Return a risk title naming the control and the process, at most 200 characters."""
    title = f"{control.title} for {process.name}"
    return title[:200]


def _link_control(risk, control, effectiveness, user):
    """
    Link the control to the risk and record the change in the risk's history.

    If the link already exists, its effectiveness is updated to match this
    outcome. Inputs: the risk, the control, the effectiveness value and the
    logged-in user. Output: nothing.
    """
    before = snapshot_control_links(risk)
    link = risk.control_links.filter(control=control).first()
    if link is None:
        RiskControl.objects.create(risk=risk, control=control, effectiveness=effectiveness)
    elif link.effectiveness != effectiveness:
        link.effectiveness = effectiveness
        link.save(update_fields=["effectiveness"])
    record_control_link_changes(risk, before, snapshot_control_links(risk), user)
