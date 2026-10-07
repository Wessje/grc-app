"""
Logic for the assessment pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Creating an assessment needs
the "add assessment" permission. Editing, archiving and restoring need
"change assessment". Viewing the lists and an assessment's page needs only a login.
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from assessments.effects import apply_completed_review, save_review_lines
from assessments.filters import (
    AssessmentFilterForm,
    column_headings,
    filter_and_sort_assessments,
    valid_choices,
    with_outcome_counts,
)
from assessments.forms import (
    AssessmentForm,
    ControlLineFormSet,
    NewRiskFormSet,
    ProcessReviewForm,
    RiskLineFormSet,
    control_line_initial,
    new_risk_initial,
    risk_line_initial,
)
from assessments.models import Assessment
from controls.models import Control
from processes.models import Process
from risks.models import Risk


def assessment_list(request):
    """
    Show assessments that are not archived, filtered and sorted as chosen.

    Input: the web request; the choices are in the web address. Output: the
    list page. By default it shows every non-archived assessment, newest
    review date first.
    """
    filter_form = AssessmentFilterForm(request.GET)
    choices = valid_choices(filter_form)
    assessments = filter_and_sort_assessments(choices)
    return render(request, "assessments/assessment_list.html", {
        "assessments": assessments,
        "filter_form": filter_form,
        "columns": column_headings(request.GET, choices.get("sort")),
        "is_filtered": any(choices.get(name) for name in ["assessment_type", "status", "q"]),
    })


def assessment_detail(request, pk):
    """
    Show one assessment, including its finding, evidence and outcome.

    Inputs: the web request and the assessment's record number.
    Output: the detail page, or a "not found" page if no such assessment exists.
    An archived assessment can still be opened directly.
    """
    assessment = get_object_or_404(
        Assessment.objects.select_related("risk", "control", "process").prefetch_related(
            "control_results__control", "control_results__risk", "risk_reviews__risk"
        ),
        pk=pk,
    )
    return render(request, "assessments/assessment_detail.html", {"assessment": assessment})


@permission_required("assessments.add_assessment", raise_exception=True)
def assessment_create(request):
    """
    Start an assessment by choosing the process or solution it covers.

    Input: the web request. Output: the review form. The controls in scope
    and the current risks appear once a process or solution is chosen.
    Saving as Complete adds or updates those risks. An assessment that
    already names a single risk or a single control is still edited on its
    own form.
    """
    return _save_process_review(request, process=None, assessment=None)


@permission_required("assessments.change_assessment", raise_exception=True)
def assessment_edit(request, pk):
    """
    Show the edit form for an assessment, and save the changes once they pass validation.

    Inputs: the web request and the assessment's record number.
    Output: the form again with error messages, or – on success – a redirect
    to the detail page. Archived assessments are read-only, so editing them is refused.
    """
    assessment = get_object_or_404(Assessment, pk=pk)
    if assessment.archived_at is not None:
        raise PermissionDenied(
            "Archived assessments are read-only. Restore the assessment to edit it."
        )
    if assessment.assessment_type == Assessment.AssessmentType.PROCESS_REVIEW:
        return _save_process_review(request, assessment.process, assessment)
    if request.method == "POST":
        form = AssessmentForm(request.POST, instance=assessment)
        if form.is_valid():
            form.save()
            messages.success(request, f"{assessment.assessment_id} updated.")
            return redirect("assessments:assessment_detail", pk=assessment.pk)
    else:
        form = AssessmentForm(instance=assessment)
    return render(request, "assessments/assessment_form.html", {
        "form": form, "assessment": assessment,
    })


@permission_required("assessments.add_assessment", raise_exception=True)
def process_review_create(request, process_pk):
    """
    Start a review of one process or solution.

    Input: the web request and the process's record number. Output: the
    review form, or – on success – a redirect to the new assessment.
    An archived process or solution cannot be reviewed.
    """
    process = get_object_or_404(Process, pk=process_pk)
    if process.archived_at is not None:
        raise PermissionDenied("Archived records are read-only. Restore this one to review it.")
    return _save_process_review(request, process, assessment=None)


def _save_process_review(request, process, assessment):
    """
    Show the process review form, and save it once every line passes.

    Inputs: the web request, the process when the review was opened from
    that record (None from New assessment), and the assessment being edited
    (None when creating). Output: the form again with errors, or a redirect
    to the assessment. Choosing a different process or solution reloads the
    controls and risks instead of saving. When the status is Complete, risks
    are created or updated as the lines say.
    """
    creating = assessment is None
    if process is None and assessment is not None:
        process = assessment.process
    if request.method == "POST":
        posted_process = _posted_process(request)
        # The type has to be set before the form checks the rules, so a
        # process review is not treated as a single control test.
        draft = assessment if assessment is not None else Assessment(
            assessment_type=Assessment.AssessmentType.PROCESS_REVIEW
        )
        draft.assessment_type = Assessment.AssessmentType.PROCESS_REVIEW
        if posted_process is not None:
            draft.process = posted_process
        reason = _reload_reason(request, posted_process)
        if reason:
            header = ProcessReviewForm(request.POST, instance=draft)
            header.is_valid()
            if reason == "show" and posted_process is not None and request.POST.get("loaded_process"):
                messages.info(
                    request,
                    f"Controls and risks are now for {posted_process.name}. Save to keep them on this assessment.",
                )
            return _render_process_review(
                request, header, posted_process, assessment,
                bind_posted_lines=(reason == "add"),
            )
        status = request.POST.get("status", Assessment.Status.PLANNED)
        review_date = request.POST.get("review_date") or None
        line_kwargs = {
            "process": posted_process,
            "assessment_status": status,
            "review_date": review_date,
        }
        header = ProcessReviewForm(request.POST, instance=draft)
        control_formset = ControlLineFormSet(
            request.POST,
            prefix="controls",
            form_kwargs={
                "process": posted_process,
                "assessment": draft,
                "assessment_status": status,
            },
        )
        risk_formset = RiskLineFormSet(
            request.POST, prefix="risks", form_kwargs=line_kwargs
        )
        new_risk_formset = NewRiskFormSet(
            request.POST, prefix="new_risks", form_kwargs=line_kwargs
        )
        formsets_valid = (
            control_formset.is_valid() and risk_formset.is_valid() and new_risk_formset.is_valid()
        )
        if header.is_valid() and formsets_valid:
            included = (
                control_formset.included_count
                + risk_formset.included_count
                + new_risk_formset.included_count
            )
            if header.cleaned_data["status"] == Assessment.Status.COMPLETE and included == 0:
                header.add_error(None, "Include at least one control or one risk.")
            else:
                try:
                    saved = _store_process_review(
                        header, control_formset, risk_formset, new_risk_formset, request.user
                    )
                except ValidationError:
                    header.add_error(
                        None,
                        "A risk could not be saved from this review. Check the scores and the category.",
                    )
                else:
                    verb = "created" if creating else "updated"
                    messages.success(request, f"{saved.assessment_id} {verb}.")
                    return redirect("assessments:assessment_detail", pk=saved.pk)
        return _render_process_review(
            request, header, posted_process, assessment,
            control_formset=control_formset,
            risk_formset=risk_formset,
            new_risk_formset=new_risk_formset,
        )
    header = ProcessReviewForm(
        instance=assessment,
        initial={"process": process.pk} if process is not None and assessment is None else None,
    )
    return _render_process_review(request, header, process, assessment, bind_posted_lines=False)


def _posted_process(request):
    """
    Return the process or solution chosen on the form, or None.

    Input: the web request. Output: the Process, or None when the choice is
    missing or not a real record. An archived record is not accepted for a
    new choice; the form's own list enforces that for a normal save.
    """
    raw = request.POST.get("process")
    if not raw:
        return None
    return Process.objects.filter(pk=raw).first()


def _reload_reason(request, posted_process):
    """
    Decide whether this submission should reload the lines instead of saving.

    Input: the web request and the chosen process. Output: "add" to keep the
    posted lines and add a blank risk, "show" to load the controls and risks
    for the chosen process, or "" when the submission should be saved.
    """
    if "add_risk" in request.POST:
        return "add"
    loaded = request.POST.get("loaded_process") or ""
    if "show_lines" in request.POST or not loaded:
        return "show"
    if posted_process is None or str(posted_process.pk) != loaded:
        return "show"
    return ""


def _render_process_review(
    request, header, process, assessment, bind_posted_lines=False,
    control_formset=None, risk_formset=None, new_risk_formset=None,
):
    """
    Render the process review page.

    Inputs: the request, the header form, the process whose lines to show
    (None when none is chosen yet), and the assessment being edited.
    When the formsets are passed in, those are shown (a failed save).
    Otherwise they are built for the process. Output: the HTML response.
    """
    lines_loaded = process is not None
    same_process = (
        assessment is not None and assessment.pk and process is not None
        and assessment.process_id == process.pk
    )
    saved_for_lines = assessment if same_process else None
    if lines_loaded and control_formset is None:
        if bind_posted_lines:
            posted = request.POST.copy()
            total = int(posted.get("new_risks-TOTAL_FORMS") or 0)
            posted["new_risks-TOTAL_FORMS"] = str(total + 1)
            control_formset = ControlLineFormSet(posted, prefix="controls", form_kwargs={"process": process})
            risk_formset = RiskLineFormSet(posted, prefix="risks", form_kwargs={"process": process})
            new_risk_formset = NewRiskFormSet(posted, prefix="new_risks", form_kwargs={"process": process})
        else:
            control_formset = ControlLineFormSet(
                prefix="controls",
                initial=control_line_initial(process, saved_for_lines),
                form_kwargs={"process": process},
            )
            risk_formset = RiskLineFormSet(
                prefix="risks",
                initial=risk_line_initial(process, saved_for_lines),
                form_kwargs={"process": process},
            )
            new_risk_formset = NewRiskFormSet(
                prefix="new_risks",
                initial=new_risk_initial(process, saved_for_lines),
                form_kwargs={"process": process},
            )
    return render(request, "assessments/process_review_form.html", {
        "form": header,
        "process": process,
        "assessment": assessment if assessment is not None and assessment.pk else None,
        "lines_loaded": lines_loaded,
        "control_formset": control_formset,
        "risk_formset": risk_formset,
        "new_risk_formset": new_risk_formset,
        "control_rows": _rows_with_subjects(control_formset, "control_id", Control) if control_formset else [],
        "risk_rows": _rows_with_subjects(risk_formset, "risk_id", Risk) if risk_formset else [],
    })


def _store_process_review(header, control_formset, risk_formset, new_risk_formset, user):
    """
    Save the review and apply it to the register when it is Complete.

    Inputs: the valid header form, the three valid line formsets and the
    logged-in user. Output: the saved assessment. The process is the one
    chosen on the form. If applying a line fails, nothing from this save is kept.
    """
    with transaction.atomic():
        assessment = header.save(commit=False)
        assessment.assessment_type = Assessment.AssessmentType.PROCESS_REVIEW
        assessment.risk = None
        assessment.control = None
        assessment.outcome = ""
        assessment.findings = ""
        assessment.evidence = ""
        assessment.save()
        save_review_lines(
            assessment,
            [row for row in control_formset.cleaned_data if row],
            [row for row in risk_formset.cleaned_data if row],
            [row for row in new_risk_formset.cleaned_data if row],
        )
        apply_completed_review(assessment, user)
    return assessment


def _rows_with_subjects(formset, id_field, model):
    """
    Pair each line form with the control or risk it is about.

    Inputs: the formset, the hidden id field name, and the model to load.
    Output: a list of {"form", "subject"} in form order, for the template.
    """
    ids = []
    for form in formset:
        raw = form[id_field].value()
        ids.append(int(raw) if raw else None)
    found = model.objects.in_bulk([pk for pk in ids if pk])
    return [{"form": form, "subject": found.get(pk)} for form, pk in zip(formset, ids)]


def archive_assessment(assessment):
    """
    Archive an assessment (take it out of the list without deleting it).

    Input: the assessment. Output: nothing. Sets "Archived at" to now. Does
    nothing if it is already archived. The finding, evidence and outcome are kept.
    """
    if assessment.archived_at is not None:
        return
    assessment.archived_at = timezone.now()
    assessment.save()


def restore_assessment(assessment):
    """
    Restore an archived assessment to the list.

    Input: the assessment. Output: nothing. Clears "Archived at". Does nothing
    if the assessment is not archived.
    """
    if assessment.archived_at is None:
        return
    assessment.archived_at = None
    assessment.save()


def archived_assessment_list(request):
    """
    Show archived assessments, most recently archived first.

    Input: the web request. Output: the archive page.
    """
    assessments = with_outcome_counts(
        Assessment.objects.filter(archived_at__isnull=False)
        .select_related("risk", "control", "process")
        .order_by("-archived_at")
    )
    return render(request, "assessments/archived_assessment_list.html", {
        "assessments": assessments,
    })


@permission_required("assessments.change_assessment", raise_exception=True)
def assessment_archive(request, pk):
    """
    Ask for confirmation, then archive an assessment.

    Inputs: the web request and the assessment's record number.
    Output: the confirmation page (first visit), or – after confirming – a
    redirect to the list. An already archived assessment goes to its detail page.
    """
    assessment = get_object_or_404(Assessment, pk=pk)
    if assessment.archived_at is not None:
        messages.info(request, f"{assessment.assessment_id} is already archived.")
        return redirect("assessments:assessment_detail", pk=assessment.pk)
    if request.method == "POST":
        archive_assessment(assessment)
        messages.success(
            request, f"{assessment.assessment_id} archived. Find it under Archived assessments."
        )
        return redirect("assessments:assessment_list")
    return render(request, "assessments/assessment_archive_confirm.html", {
        "assessment": assessment,
    })


@require_POST
@permission_required("assessments.change_assessment", raise_exception=True)
def assessment_restore(request, pk):
    """
    Restore an archived assessment to the list.

    Inputs: the web request (must be a form submission, not a link) and the
    assessment's record number. Output: a redirect to the assessment's detail page.
    """
    assessment = get_object_or_404(Assessment, pk=pk)
    if assessment.archived_at is not None:
        restore_assessment(assessment)
        messages.success(request, f"{assessment.assessment_id} restored to the list.")
    return redirect("assessments:assessment_detail", pk=assessment.pk)
