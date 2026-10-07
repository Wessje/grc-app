"""
Which reviews to show on a risk page and on a control page.

A process or solution review does not name the risk or the control on the
assessment itself. The link is on the line. These helpers collect both the
older single-subject reviews and those lines, and skip archived assessments.
"""

def reviews_for_risk(risk):
    """
    Return the reviews that cover this risk, newest first.

    Input: a risk. Output: a list of {"assessment", "outcome"}. A direct
    risk review uses its own outcome. A process review that created or
    updated the risk uses that control's outcome. A reassessment says
    "Closed" when the line closed the risk, otherwise "Reassessed".
    A line that was not included is left out.
    """
    rows = {}
    for assessment in risk.assessments.filter(archived_at__isnull=True):
        _add_review(rows, assessment, assessment.get_outcome_display() or "—")
    included = dict(include=True, assessment__archived_at__isnull=True)
    for line in risk.source_control_lines.filter(**included).select_related("assessment"):
        _add_review(rows, line.assessment, line.get_outcome_display() or "—")
    for line in risk.reassessments.filter(**included).select_related("assessment"):
        outcome = "Closed" if line.close_risk else "Reassessed"
        _add_review(rows, line.assessment, outcome)
    return _newest_first(rows)


def reviews_for_control(control):
    """
    Return the tests of this control, newest first.

    Input: a control. Output: a list of {"assessment", "outcome"}. Includes
    a direct control test and a process review that included this control.
    The outcome is the one recorded for this control.
    """
    rows = {}
    for assessment in control.assessments.filter(archived_at__isnull=True):
        _add_review(rows, assessment, assessment.get_outcome_display() or "—")
    for line in control.process_assessment_lines.filter(
        include=True, assessment__archived_at__isnull=True
    ).select_related("assessment"):
        _add_review(rows, line.assessment, line.get_outcome_display() or "—")
    return _newest_first(rows)


def _add_review(rows, assessment, outcome):
    """Keep one row per assessment. A close replaces a milder outcome."""
    current = rows.get(assessment.pk)
    if current is None:
        rows[assessment.pk] = {"assessment": assessment, "outcome": outcome}
    elif outcome == "Closed":
        current["outcome"] = "Closed"
    elif current["outcome"] in ("—", "Reassessed"):
        current["outcome"] = outcome


def _newest_first(rows):
    """Return the rows sorted by review date, then record number, newest first."""
    return sorted(
        rows.values(),
        key=lambda row: (row["assessment"].review_date, row["assessment"].id),
        reverse=True,
    )
