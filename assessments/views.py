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
from assessments.forms import (
    AssessmentForm,
    ControlLineFormSet,
    ProcessReviewForm,
    RiskLineFormSet,
    control_line_initial,
    risk_line_initial,
)
from assessments.models import Assessment
from controls.models import Control
from processes.models import Process
from risks.models import Risk


def assessment_list(request):
    """
    Show assessments that are not archived, newest review date first.

    Input: the web request. Output: the list page.
    """
    assessments = (
        Assessment.objects.filter(archived_at__isnull=True)
        .select_related("risk", "control", "process")
        .order_by("-review_date", "-id")
    )
    return render(request, "assessments/assessment_list.html", {"assessments": assessments})


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
    Show the "New assessment" form, and save it once it passes validation.

    Input: the web request (a blank form on first visit; the filled-in form
    when submitted). Output: the form again with error messages, or – on
    success – a redirect to the new assessment's detail page. The Assessment
    ID is assigned automatically on save.
    """
    if request.method == "POST":
        form = AssessmentForm(request.POST)
        if form.is_valid():
            assessment = form.save()
            messages.success(request, f"{assessment.assessment_id} created.")
            return redirect("assessments:assessment_detail", pk=assessment.pk)
    else:
        form = AssessmentForm()
    return render(request, "assessments/assessment_form.html", {"form": form, "assessment": None})


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

    Inputs: the web request, the process, and the assessment being edited
    (None when creating). Output: the form again with errors, or a redirect
    to the assessment. When the status is Complete, risks are created,
    updated or closed as the lines say.
    """
    creating = assessment is None
    if request.method == "POST":
        status = request.POST.get("status", Assessment.Status.PLANNED)
        # The type and process have to be set before the form checks the
        # rules, so a process review is not treated as a single control test.
        if creating:
            assessment = Assessment(
                assessment_type=Assessment.AssessmentType.PROCESS_REVIEW,
                process=process,
            )
        header = ProcessReviewForm(request.POST, instance=assessment)
        control_formset = ControlLineFormSet(
            request.POST,
            prefix="controls",
            form_kwargs={
                "process": process,
                "assessment": assessment,
                "assessment_status": status,
            },
        )
        risk_formset = RiskLineFormSet(
            request.POST,
            prefix="risks",
            form_kwargs={"process": process, "assessment_status": status},
        )
        if header.is_valid() and control_formset.is_valid() and risk_formset.is_valid():
            included = control_formset.included_count + risk_formset.included_count
            if header.cleaned_data["status"] == Assessment.Status.COMPLETE and included == 0:
                header.add_error(None, "Include at least one control or one risk.")
            else:
                try:
                    saved = _store_process_review(
                        header, control_formset, risk_formset, process, request.user
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
    else:
        header = ProcessReviewForm(instance=assessment)
        control_formset = ControlLineFormSet(
            prefix="controls",
            initial=control_line_initial(process, assessment),
            form_kwargs={"process": process, "assessment": assessment},
        )
        risk_formset = RiskLineFormSet(
            prefix="risks",
            initial=risk_line_initial(process, assessment),
            form_kwargs={"process": process},
        )
    return render(request, "assessments/process_review_form.html", {
        "form": header,
        "process": process,
        "assessment": assessment,
        "control_formset": control_formset,
        "risk_formset": risk_formset,
        "control_rows": _rows_with_subjects(control_formset, "control_id", Control),
        "risk_rows": _rows_with_subjects(risk_formset, "risk_id", Risk),
    })


def _store_process_review(header, control_formset, risk_formset, process, user):
    """
    Save the review and apply it to the register when it is Complete.

    Inputs: the valid header form, the two valid line formsets, the process
    and the logged-in user. Output: the saved assessment. If applying a line
    fails, nothing from this save is kept.
    """
    with transaction.atomic():
        assessment = header.save(commit=False)
        assessment.assessment_type = Assessment.AssessmentType.PROCESS_REVIEW
        assessment.process = process
        assessment.risk = None
        assessment.control = None
        assessment.outcome = ""
        assessment.findings = ""
        assessment.evidence = ""
        assessment.save()
        save_review_lines(
            assessment,
            control_formset.cleaned_data,
            risk_formset.cleaned_data,
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
    assessments = (
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
