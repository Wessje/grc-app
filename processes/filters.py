"""
Filters, text search and sorting for the process and solution list.

The choices arrive in the web address (for example ?kind=solution&q=email).
They are checked like any other input: an unknown value is ignored, and only
the listed fields can be sorted on.
"""

from django import forms
from django.db.models import Q

from processes.models import Process


class ProcessFilterForm(forms.Form):
    """The filter bar above the process list. Every field is optional."""

    kind = forms.ChoiceField(
        label="Type",
        choices=[("", "Any type")] + list(Process.Kind.choices),
        required=False,
    )
    q = forms.CharField(
        label="Search",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search name or description"}),
    )
    sort = forms.ChoiceField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        """Limit the sort field to the columns the list actually offers."""
        super().__init__(*args, **kwargs)
        self.fields["sort"].choices = SORT_CHOICES


# Columns that can be sorted: sort key -> (heading, database field).
SORTABLE_COLUMNS = {
    "id": ("ID", "id"),
    "name": ("Name", "name"),
    "kind": ("Type", "kind"),
    "owner": ("Owner", "owner"),
}
DEFAULT_SORT = "id"
SORT_CHOICES = [(key, key) for key in SORTABLE_COLUMNS] + [
    (f"-{key}", f"-{key}") for key in SORTABLE_COLUMNS
]


def valid_choices(form):
    """
    Return the filter choices that passed validation.

    Input: a filter form filled from the web address. Output: a dictionary
    of the valid choices only. An invalid value is left out, so that filter
    falls back to its default.
    """
    form.is_valid()
    return getattr(form, "cleaned_data", {})


def filter_and_sort_processes(choices):
    """
    Return the processes and solutions for the given filter choices.

    Input: the valid choices from `valid_choices`. Output: the matching
    non-archived records, sorted by ID unless another sort was chosen.
    Archived records are never included.
    """
    processes = Process.objects.filter(archived_at__isnull=True)
    if choices.get("kind"):
        processes = processes.filter(kind=choices["kind"])

    search_text = choices.get("q", "").strip()
    if search_text:
        processes = processes.filter(
            Q(name__icontains=search_text) | Q(description__icontains=search_text)
        )

    sort = choices.get("sort") or DEFAULT_SORT
    descending = sort.startswith("-")
    field = SORTABLE_COLUMNS[sort.lstrip("-")][1]
    direction = "-" if descending else ""
    tie = "-id" if descending else "id"
    if field == "id":
        return processes.order_by(f"{direction}id")
    return processes.order_by(f"{direction}{field}", tie)


def column_headings(query_params, current_sort):
    """
    Build the sortable column headings for the process table.

    Inputs: the current web address parameters and the current sort.
    Output: a list of dictionaries with each column's label, the address
    that sorts by it (keeping the current filters), and an arrow on the
    column currently sorted. Clicking a sorted column reverses it.
    """
    current_sort = current_sort or DEFAULT_SORT
    headings = []
    for key, (label, _) in SORTABLE_COLUMNS.items():
        params = query_params.copy()
        params["sort"] = f"-{key}" if current_sort == key else key
        arrow = ""
        if current_sort == key:
            arrow = "▲"
        elif current_sort == f"-{key}":
            arrow = "▼"
        headings.append({"label": label, "query": params.urlencode(), "arrow": arrow})
    return headings
