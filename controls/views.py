"""
Logic for the control register pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Controls are still created
and edited in the admin screen.
"""

from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from controls.models import Control


def control_list(request):
    """
    Show the control register: controls that are not archived.

    Input: the web request. Output: the list page. Each row includes how
    many risks that control addresses.
    """
    controls = (
        Control.objects.filter(archived_at__isnull=True)
        .annotate(risk_count=Count("risk_links"))
    )
    return render(request, "controls/control_list.html", {"controls": controls})


def control_detail(request, pk):
    """
    Show one control and the risks it addresses.

    Inputs: the web request and the control's record number.
    Output: the detail page, or a "not found" page if no such control exists.
    An archived control can still be opened directly.
    """
    control = get_object_or_404(Control, pk=pk)
    risk_links = control.risk_links.select_related("risk", "risk__category")
    return render(request, "controls/control_detail.html", {
        "control": control,
        "risk_links": risk_links,
    })
