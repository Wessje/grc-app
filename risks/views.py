"""
Logic for each risk register page. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py.
"""

from django.shortcuts import get_object_or_404, render

from risks.models import Risk

# Statuses shown in the register by default. Closed risks are reached
# through the status filter (Step 7).
ACTIVE_STATUSES = [Risk.Status.OPEN, Risk.Status.IN_TREATMENT, Risk.Status.MONITORING]


def risk_list(request):
    """
    Show the register: risks that are not archived and not Closed.

    Input: the web request. Output: the list page.
    """
    risks = (
        Risk.objects.filter(archived_at__isnull=True, status__in=ACTIVE_STATUSES)
        .select_related("category")  # fetch categories in the same query
    )
    return render(request, "risks/risk_list.html", {"risks": risks})


def risk_detail(request, pk):
    """
    Show all fields of one risk.

    Inputs: the web request and the risk's record number.
    Output: the detail page, or a "not found" page if no such risk exists.
    Archived risks can still be viewed here.
    """
    risk = get_object_or_404(Risk.objects.select_related("category"), pk=pk)
    return render(request, "risks/risk_detail.html", {"risk": risk})
