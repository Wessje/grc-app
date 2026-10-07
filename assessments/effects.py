"""
Applies a completed process or solution review to the risk register.

A control that is unsatisfactory or only partly satisfactory creates an
open risk, or updates the open risk already linked to that process and
that control. A satisfactory result does not create a risk and does not
close one. A risk included in the review is updated from its line, and
is closed only when that line says to close it.
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


def save_review_lines(assessment, control_rows, risk_rows):
    """
    Store the control and risk lines for a process or solution review.

    Inputs: the saved assessment, and the cleaned rows from the two forms.
    Output: nothing. A row left unticked is stored too, so the next edit
    shows that choice. The risk a control line already created is kept.
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
        line.include = bool(row.get("include"))
        line.findings = row.get("findings") or ""
        line.evidence = row.get("evidence") or ""
        line.likelihood = row.get("likelihood")
        line.impact = row.get("impact")
        line.close_risk = bool(row.get("close_risk"))
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
        for line in assessment.risk_reviews.select_related("risk"):
            _apply_risk_line(line, user)


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


def _apply_risk_line(line, user):
    """Update a risk from its reassessment line, and close it only when asked."""
    if not line.include:
        return
    risk = line.risk
    risk.description = line.findings
    if line.likelihood and line.impact:
        risk.inherent_likelihood = line.likelihood
        risk.inherent_impact = line.impact
    if line.close_risk:
        risk.status = Risk.Status.CLOSED
    risk.full_clean()
    save_risk_with_history(risk, user)


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
