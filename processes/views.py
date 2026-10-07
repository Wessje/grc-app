"""
Logic for the process and solution pages. Each function receives the web
request and returns the HTML page to show.

Login is required for every page; this is enforced project-wide by
LoginRequiredMiddleware in config/settings.py. Creating one needs the
"add process" permission. Editing, archiving and restoring need "change
process". Viewing the lists and a record's page needs only a login.
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from processes.forms import ProcessControlLinkFormSet, ProcessForm
from processes.models import Process


def process_list(request):
    """
    Show processes and solutions that are not archived.

    Input: the web request. Output: the list page.
    """
    processes = Process.objects.filter(archived_at__isnull=True)
    return render(request, "processes/process_list.html", {"processes": processes})


def process_detail(request, pk):
    """
    Show one process or solution.

    Inputs: the web request and the record number.
    Output: the detail page, or a "not found" page if no such record exists.
    An archived record can still be opened directly.
    """
    process = get_object_or_404(Process, pk=pk)
    risks = process.risks.select_related("category").order_by("id")
    control_links = process.control_links.select_related("control")
    assessments = process.assessments.filter(archived_at__isnull=True).order_by("-review_date", "-id")
    return render(request, "processes/process_detail.html", {
        "process": process,
        "risks": risks,
        "control_links": control_links,
        "assessments": assessments,
    })


@permission_required("processes.add_process", raise_exception=True)
def process_create(request):
    """
    Show the "New process or solution" form, and save it once it passes validation.

    Input: the web request. Output: the form again with error messages, or –
    on success – a redirect to the new record's page. The ID is assigned
    automatically on save.
    """
    process = Process()
    if request.method == "POST":
        form = ProcessForm(request.POST)
        link_formset = ProcessControlLinkFormSet(request.POST, instance=process)
        if form.is_valid() and link_formset.is_valid():
            process = form.save()
            link_formset.instance = process
            link_formset.save()
            messages.success(request, f"{process.process_id} created.")
            return redirect("processes:process_detail", pk=process.pk)
    else:
        form = ProcessForm()
        link_formset = ProcessControlLinkFormSet(instance=process)
    return render(request, "processes/process_form.html", {
        "form": form, "process": None, "link_formset": link_formset,
    })


@permission_required("processes.change_process", raise_exception=True)
def process_edit(request, pk):
    """
    Show the edit form, and save the changes once they pass validation.

    Inputs: the web request and the record number.
    Output: the form again with error messages, or – on success – a redirect
    to the detail page. Archived records are read-only, so editing them is refused.
    """
    process = get_object_or_404(Process, pk=pk)
    if process.archived_at is not None:
        raise PermissionDenied(
            "Archived records are read-only. Restore this one to edit it."
        )
    if request.method == "POST":
        form = ProcessForm(request.POST, instance=process)
        link_formset = ProcessControlLinkFormSet(request.POST, instance=process)
        if form.is_valid() and link_formset.is_valid():
            form.save()
            link_formset.save()
            messages.success(request, f"{process.process_id} updated.")
            return redirect("processes:process_detail", pk=process.pk)
    else:
        form = ProcessForm(instance=process)
        link_formset = ProcessControlLinkFormSet(instance=process)
    return render(request, "processes/process_form.html", {
        "form": form, "process": process, "link_formset": link_formset,
    })


def archive_process(process):
    """
    Archive a process or solution without deleting it.

    Input: the record. Output: nothing. Sets "Archived at" to now. Does
    nothing if it is already archived.
    """
    if process.archived_at is not None:
        return
    process.archived_at = timezone.now()
    process.save()


def restore_process(process):
    """
    Restore an archived process or solution to the list.

    Input: the record. Output: nothing. Clears "Archived at". Does nothing
    if it is not archived.
    """
    if process.archived_at is None:
        return
    process.archived_at = None
    process.save()


def archived_process_list(request):
    """
    Show archived processes and solutions, most recently archived first.

    Input: the web request. Output: the archive page.
    """
    processes = Process.objects.filter(archived_at__isnull=False).order_by("-archived_at")
    return render(request, "processes/archived_process_list.html", {"processes": processes})


@permission_required("processes.change_process", raise_exception=True)
def process_archive(request, pk):
    """
    Ask for confirmation, then archive a process or solution.

    Inputs: the web request and the record number.
    Output: the confirmation page, or – after confirming – a redirect to the
    list. An already archived record goes to its detail page.
    """
    process = get_object_or_404(Process, pk=pk)
    if process.archived_at is not None:
        messages.info(request, f"{process.process_id} is already archived.")
        return redirect("processes:process_detail", pk=process.pk)
    if request.method == "POST":
        archive_process(process)
        messages.success(request, f"{process.process_id} archived. Find it under Archived processes.")
        return redirect("processes:process_list")
    return render(request, "processes/process_archive_confirm.html", {"process": process})


@require_POST
@permission_required("processes.change_process", raise_exception=True)
def process_restore(request, pk):
    """
    Restore an archived process or solution.

    Inputs: the web request (must be a form submission, not a link) and the
    record number. Output: a redirect to the detail page.
    """
    process = get_object_or_404(Process, pk=pk)
    if process.archived_at is not None:
        restore_process(process)
        messages.success(request, f"{process.process_id} restored to the list.")
    return redirect("processes:process_detail", pk=process.pk)
