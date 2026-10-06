"""
Logic for each risk register page. Each function receives the web request
and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Creating and editing also
require the matching permission (superusers have all permissions).
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from controls.forms import RiskControlLinkFormSet
from controls.links import record_control_link_changes, snapshot_control_links
from risks.filters import (
    RegisterFilterForm,
    column_headings,
    filter_and_sort_risks,
    valid_choices,
)
from risks.forms import RiskForm
from risks.heatmap import build_heat_map
from risks.history import archive_risk, restore_risk, save_risk_with_history
from risks.models import Risk


def risk_list(request):
    """
    Show the register, filtered, searched and sorted as chosen in the filter bar.

    Input: the web request; the choices are in the web address. Output: the
    list page, with a heat map of the risks shown. By default it shows
    non-archived Open, In treatment and Monitoring risks, sorted by Risk ID.
    """
    filter_form = RegisterFilterForm(request.GET)
    choices = valid_choices(filter_form)
    # list() fetches the risks once, for both the heat map and the table.
    risks = list(filter_and_sort_risks(choices))
    return render(request, "risks/risk_list.html", {
        "risks": risks,
        "heat_map": build_heat_map(risks),
        "filter_form": filter_form,
        "columns": column_headings(request.GET, choices.get("sort")),
        "is_filtered": any(choices.get(name) for name in ["status", "category", "rating", "q"]),
    })


def risk_detail(request, pk):
    """
    Show all fields of one risk and its change history, newest first.

    Inputs: the web request and the risk's record number.
    Output: the detail page, or a "not found" page if no such risk exists.
    Archived risks can still be viewed here.
    """
    risk = get_object_or_404(Risk.objects.select_related("category"), pk=pk)
    changes = risk.changes.select_related("changed_by")
    control_links = risk.control_links.select_related("control")
    return render(request, "risks/risk_detail.html", {
        "risk": risk,
        "changes": changes,
        "control_links": control_links,
    })


@permission_required("risks.add_risk", raise_exception=True)
def risk_create(request):
    """
    Show the "New risk" form, and save the risk once it passes validation.

    Input: the web request (a blank form on first visit; the filled-in form
    when submitted). Output: the form again with error messages, or – on
    success – a redirect to the new risk's detail page.
    """
    risk = Risk()
    if request.method == "POST":
        form = RiskForm(request.POST)
        link_formset = RiskControlLinkFormSet(request.POST, instance=risk)
        if form.is_valid() and link_formset.is_valid():
            risk = form.save(commit=False)
            save_risk_with_history(risk, request.user)
            link_formset.instance = risk
            before = {}
            link_formset.save()
            record_control_link_changes(
                risk, before, snapshot_control_links(risk), request.user
            )
            messages.success(request, f"{risk.risk_id} created.")
            return redirect("risks:risk_detail", pk=risk.pk)
    else:
        form = RiskForm()
        link_formset = RiskControlLinkFormSet(instance=risk)
    return render(request, "risks/risk_form.html", {
        "form": form, "risk": None, "link_formset": link_formset,
    })


@permission_required("risks.change_risk", raise_exception=True)
def risk_edit(request, pk):
    """
    Show the edit form for a risk, and save the changes once they pass validation.

    Inputs: the web request and the risk's record number.
    Output: the form again with error messages, or – on success – a redirect
    to the detail page. Archived risks are read-only, so editing them is refused.
    """
    risk = get_object_or_404(Risk, pk=pk)
    if risk.archived_at is not None:
        raise PermissionDenied("Archived risks are read-only. Restore the risk to edit it.")
    if request.method == "POST":
        form = RiskForm(request.POST, instance=risk)
        link_formset = RiskControlLinkFormSet(request.POST, instance=risk)
        if form.is_valid() and link_formset.is_valid():
            before = snapshot_control_links(risk)
            save_risk_with_history(form.save(commit=False), request.user)
            link_formset.save()
            record_control_link_changes(
                risk, before, snapshot_control_links(risk), request.user
            )
            messages.success(request, f"{risk.risk_id} updated.")
            return redirect("risks:risk_detail", pk=risk.pk)
    else:
        form = RiskForm(instance=risk)
        link_formset = RiskControlLinkFormSet(instance=risk)
    return render(request, "risks/risk_form.html", {
        "form": form, "risk": risk, "link_formset": link_formset,
    })


def archived_risk_list(request):
    """
    Show the archive: all archived risks, most recently archived first.

    Input: the web request. Output: the archive page.
    """
    risks = (
        Risk.objects.filter(archived_at__isnull=False)
        .select_related("category")
        .order_by("-archived_at")
    )
    return render(request, "risks/archived_risk_list.html", {"risks": risks})


@permission_required("risks.change_risk", raise_exception=True)
def risk_archive(request, pk):
    """
    Ask for confirmation, then archive a risk.

    Inputs: the web request and the risk's record number.
    Output: the confirmation page (first visit), or – after confirming – a
    redirect to the register. An already archived risk goes to its detail page.
    """
    risk = get_object_or_404(Risk, pk=pk)
    if risk.archived_at is not None:
        messages.info(request, f"{risk.risk_id} is already archived.")
        return redirect("risks:risk_detail", pk=risk.pk)
    if request.method == "POST":
        archive_risk(risk, request.user)
        messages.success(request, f"{risk.risk_id} archived. Find it under Archive.")
        return redirect("risks:risk_list")
    return render(request, "risks/risk_archive_confirm.html", {"risk": risk})


@require_POST
@permission_required("risks.change_risk", raise_exception=True)
def risk_restore(request, pk):
    """
    Restore an archived risk to the register.

    Inputs: the web request (must be a form submission, not a link) and the
    risk's record number. Output: a redirect to the risk's detail page.
    """
    risk = get_object_or_404(Risk, pk=pk)
    if risk.archived_at is not None:
        restore_risk(risk, request.user)
        messages.success(request, f"{risk.risk_id} restored to the register.")
    return redirect("risks:risk_detail", pk=risk.pk)
