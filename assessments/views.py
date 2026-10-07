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
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from assessments.forms import AssessmentForm
from assessments.models import Assessment


def assessment_list(request):
    """
    Show assessments that are not archived, newest review date first.

    Input: the web request. Output: the list page.
    """
    assessments = (
        Assessment.objects.filter(archived_at__isnull=True)
        .select_related("risk", "control")
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
        Assessment.objects.select_related("risk", "control"), pk=pk
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
        .select_related("risk", "control")
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
