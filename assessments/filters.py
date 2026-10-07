"""
Filters, text search and sorting for the assessment list.

The choices arrive in the web address (for example ?status=complete&q=email).
They are checked like any other input: an unknown value is ignored, and only
the listed fields can be sorted on.
"""

from django import forms
from django.db.models import Count, Q

from assessments.models import Assessment


class AssessmentFilterForm(forms.Form):
    """The filter bar above the assessment list. Every field is optional."""

    assessment_type = forms.ChoiceField(
        label="Type",
        choices=[("", "Any type")] + list(Assessment.AssessmentType.choices),
        required=False,
    )
    status = forms.ChoiceField(
        choices=[("", "Any status")] + list(Assessment.Status.choices),
        required=False,
    )
    q = forms.CharField(
        label="Search",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search title or subject"}),
    )
    sort = forms.ChoiceField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        """Limit the sort field to the columns the list actually offers."""
        super().__init__(*args, **kwargs)
        self.fields["sort"].choices = SORT_CHOICES


# Columns that can be sorted: sort key -> (heading, database field).
# Subject and Outcome are shown, but they are not one field, so they are
# not in this list and cannot be sorted.
SORTABLE_COLUMNS = {
    "id": ("Assessment ID", "id"),
    "title": ("Title", "title"),
    "type": ("Type", "assessment_type"),
    "review_date": ("Review date", "review_date"),
    "status": ("Status", "status"),
}
# Headings in table order. None means the column is shown but not sortable.
COLUMN_ORDER = [
    ("id", "Assessment ID", True),
    ("title", "Title", True),
    ("type", "Type", True),
    ("subject", "Subject", False),
    ("review_date", "Review date", True),
    ("status", "Status", True),
    ("outcome", "Outcome", False),
]
# Newest review first, matching the list before sorting was added.
DEFAULT_SORT = "-review_date"
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


def with_outcome_counts(queryset):
    """
    Count included control outcomes on each assessment in one query.

    Input: an assessment query. Output: the same query with three counts:
    unsatisfactory, partial and satisfactory. A control left out of the
    review is not counted. The list uses these counts for the Outcome column.
    """
    included = Q(control_results__include=True)
    return queryset.annotate(
        unsatisfactory_count=Count(
            "control_results",
            filter=included & Q(control_results__outcome=Assessment.Outcome.UNSATISFACTORY),
        ),
        partial_count=Count(
            "control_results",
            filter=included & Q(control_results__outcome=Assessment.Outcome.PARTIAL),
        ),
        satisfactory_count=Count(
            "control_results",
            filter=included & Q(control_results__outcome=Assessment.Outcome.SATISFACTORY),
        ),
    )


def filter_and_sort_assessments(choices):
    """
    Return the assessments for the given filter choices.

    Input: the valid choices from `valid_choices`. Output: the matching
    non-archived assessments, newest review date first unless another sort
    was chosen. Archived assessments are never included.
    """
    assessments = with_outcome_counts(
        Assessment.objects.filter(archived_at__isnull=True).select_related(
            "risk", "control", "process"
        )
    )
    if choices.get("assessment_type"):
        assessments = assessments.filter(assessment_type=choices["assessment_type"])
    if choices.get("status"):
        assessments = assessments.filter(status=choices["status"])

    search_text = choices.get("q", "").strip()
    if search_text:
        assessments = assessments.filter(
            Q(title__icontains=search_text)
            | Q(process__name__icontains=search_text)
            | Q(control__title__icontains=search_text)
            | Q(risk__title__icontains=search_text)
        )

    return assessments.order_by(*_sort_order(choices.get("sort")))


def column_headings(query_params, current_sort):
    """
    Build the column headings for the assessment table.

    Inputs: the current web address parameters and the current sort.
    Output: a list of dictionaries with each column's label, whether it
    can be sorted, the address that sorts by it (keeping the current
    filters), and an arrow on the column currently sorted. Clicking a
    sorted column reverses it. Subject and Outcome have no sort address.
    """
    current_sort = current_sort or DEFAULT_SORT
    headings = []
    for key, label, sortable in COLUMN_ORDER:
        query = ""
        arrow = ""
        if sortable:
            params = query_params.copy()
            params["sort"] = f"-{key}" if current_sort == key else key
            query = params.urlencode()
            if current_sort == key:
                arrow = "▲"
            elif current_sort == f"-{key}":
                arrow = "▼"
        headings.append({
            "label": label, "sortable": sortable, "query": query, "arrow": arrow,
        })
    return headings


def _sort_order(sort):
    """
    Turn a sort key into the database order.

    Input: a key such as "title" or "-review_date", or empty. Output: the
    fields to order by. An empty key uses the default (newest review first).
    The assessment's record number is the tie-breaker, so equal dates stay
    in a stable order.
    """
    sort = sort or DEFAULT_SORT
    descending = sort.startswith("-")
    field = SORTABLE_COLUMNS[sort.lstrip("-")][1]
    direction = "-" if descending else ""
    tie = "-id" if descending else "id"
    if field == "id":
        return (f"{direction}id",)
    return (f"{direction}{field}", tie)
