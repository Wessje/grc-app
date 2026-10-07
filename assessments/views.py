"""
Logic for the assessment pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. These pages are read-only.
Assessments are still created and edited in the admin screen.
"""

from django.shortcuts import get_object_or_404, render

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
