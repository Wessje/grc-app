"""
Logic for the control register pages. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Creating a control needs the
"add control" permission, and editing one needs "change control". Viewing
the list and a control's page needs only a login.
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from controls.filters import ControlFilterForm, selected_framework
from controls.forms import ControlForm
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


@permission_required("controls.add_control", raise_exception=True)
def control_create(request):
    """
    Show the "New control" form, and save the control once it passes validation.

    Input: the web request (a blank form on first visit; the filled-in form
    when submitted). Output: the form again with error messages, or – on
    success – a redirect to the new control's detail page. The Control ID is
    assigned automatically on save.
    """
    if request.method == "POST":
        form = ControlForm(request.POST)
        if form.is_valid():
            control = form.save()
            messages.success(request, f"{control.control_id} created.")
            return redirect("controls:control_detail", pk=control.pk)
    else:
        form = ControlForm()
    return render(request, "controls/control_form.html", {"form": form, "control": None})


@permission_required("controls.change_control", raise_exception=True)
def control_edit(request, pk):
    """
    Show the edit form for a control, and save the changes once they pass validation.

    Inputs: the web request and the control's record number.
    Output: the form again with error messages, or – on success – a redirect
    to the detail page. Archived controls are read-only, so editing them is refused.
    """
    control = get_object_or_404(Control, pk=pk)
    if control.archived_at is not None:
        raise PermissionDenied(
            "Archived controls are read-only. Restore the control to edit it."
        )
    if request.method == "POST":
        form = ControlForm(request.POST, instance=control)
        if form.is_valid():
            form.save()
            messages.success(request, f"{control.control_id} updated.")
            return redirect("controls:control_detail", pk=control.pk)
    else:
        form = ControlForm(instance=control)
    return render(request, "controls/control_form.html", {"form": form, "control": control})
