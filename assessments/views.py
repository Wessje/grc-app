"""
Logic for the assessment pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Creating an assessment needs
the "add assessment" permission, and editing one needs "change assessment".
Viewing the list and an assessment's page needs only a login.
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

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
