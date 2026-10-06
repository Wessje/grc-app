"""
Logic for the control register pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Controls are still created
and edited in the admin screen.
"""

from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from controls.filters import ControlFilterForm, selected_framework
from controls.models import Control


def control_list(request):
    """
    Show the control register: controls that are not archived.

    Input: the web request. A framework choice in the address limits the
    list to controls mapped to that framework. Output: the list page.
    Each row includes how many risks that control addresses.
    """
    filter_form = ControlFilterForm(request.GET)
    framework = selected_framework(filter_form)
    controls = Control.objects.filter(archived_at__isnull=True)
    if framework:
        controls = controls.filter(requirement_links__requirement__framework=framework)
    # distinct=True keeps the risk count correct when the framework filter
    # joins a control to more than one requirement.
    controls = controls.annotate(risk_count=Count("risk_links", distinct=True)).distinct()
    return render(request, "controls/control_list.html", {
        "controls": controls,
        "filter_form": filter_form,
        "is_filtered": bool(framework),
    })


def control_detail(request, pk):
    """
    Show one control, the risks it addresses, and the framework requirements it maps to.

    Inputs: the web request and the control's record number.
    Output: the detail page, or a "not found" page if no such control exists.
    An archived control can still be opened directly.
    """
    control = get_object_or_404(Control, pk=pk)
    risk_links = control.risk_links.select_related("risk", "risk__category")
    requirement_links = control.requirement_links.select_related("requirement")
    return render(request, "controls/control_detail.html", {
        "control": control,
        "risk_links": risk_links,
        "requirement_links": requirement_links,
    })
