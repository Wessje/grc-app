"""
Filters, text search and sorting for the risk register page.

The choices arrive in the web address (e.g. ?status=closed&sort=-score), which
anyone can edit. They are checked by `RegisterFilterForm` like any other input:
unknown values are ignored, and only listed fields can be sorted on.
"""

from django import forms
from django.db.models import Case, IntegerField, Q, Value, When

from risks.models import RATING_BANDS, Risk, RiskCategory, score_range_for_rating

# Status filter: "" (the default) shows the active statuses only.
ACTIVE = ""
ALL = "all"
ACTIVE_STATUSES = [Risk.Status.OPEN, Risk.Status.IN_TREATMENT, Risk.Status.MONITORING]
STATUS_FILTER_CHOICES = (
    [(ACTIVE, "Active (not Closed)")]
    + list(Risk.Status.choices)
    + [(ALL, "All")]
)

RATING_FILTER_CHOICES = [("", "Any rating")] + [(rating, rating) for _, rating in RATING_BANDS]

# Columns that can be sorted: sort key -> (column heading, what to sort by).
# "status" is sorted in lifecycle order (see `status_lifecycle_order`), not
# alphabetically. The rating column sorts by score, which gives the same order.
SORTABLE_COLUMNS = {
    "id": ("Risk ID", "id"),
    "title": ("Title", "title"),
    "owner": ("Owner", "owner"),
    "category": ("Category", "category__name"),
    "score": ("Inherent score", "inherent_score"),
    "rating": ("Inherent rating", "inherent_score"),
    "residual_score": ("Residual score", "residual_score"),
    "residual_rating": ("Residual rating", "residual_score"),
    "status": ("Status", "status_order"),
}
DEFAULT_SORT = "id"
# Each column can be sorted ascending ("score") or descending ("-score").
SORT_CHOICES = [(key, key) for key in SORTABLE_COLUMNS] + [
    (f"-{key}", f"-{key}") for key in SORTABLE_COLUMNS
]


class RegisterFilterForm(forms.Form):
    """The filter bar above the register. Every field is optional."""

    status = forms.ChoiceField(choices=STATUS_FILTER_CHOICES, required=False)
    category = forms.ModelChoiceField(
        queryset=RiskCategory.objects.all(), required=False, empty_label="Any category"
    )
    rating = forms.ChoiceField(choices=RATING_FILTER_CHOICES, required=False)
    q = forms.CharField(
        label="Search", max_length=100, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search title or description"}),
    )
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False, widget=forms.HiddenInput)


def valid_choices(form):
    """
    Return the filter choices that passed validation.

    Input: a filter form filled from the web address. Output: a dictionary
    of the valid choices only; an invalid value (e.g. ?status=nonsense) is
    simply left out, so that filter falls back to its default.
    """
    form.is_valid()
    return getattr(form, "cleaned_data", {})


def status_lifecycle_order():
    """Return a sort value per status: Open 0, In treatment 1, Monitoring 2, Closed 3."""
    return Case(
        *[When(status=status, then=Value(position))
          for position, status in enumerate(Risk.Status.values)],
        output_field=IntegerField(),
    )


def filter_and_sort_risks(choices):
    """
    Return the register's risks for the given filter choices.

    Input: the valid choices from `valid_choices`. Output: the matching
    non-archived risks, sorted as requested (Risk ID by default). Archived
    risks are never included; they are on the Archive page.
    """
    risks = Risk.objects.filter(archived_at__isnull=True).select_related("category")

    status = choices.get("status", ACTIVE)
    if status == ACTIVE:
        risks = risks.filter(status__in=ACTIVE_STATUSES)
    elif status != ALL:
        risks = risks.filter(status=status)

    if choices.get("category"):
        risks = risks.filter(category=choices["category"])

    if choices.get("rating"):
        lowest, highest = score_range_for_rating(choices["rating"])
        risks = risks.filter(inherent_score__gte=lowest, inherent_score__lte=highest)

    search_text = choices.get("q", "").strip()
    if search_text:
        risks = risks.filter(
            Q(title__icontains=search_text) | Q(description__icontains=search_text)
        )

    sort = choices.get("sort") or DEFAULT_SORT
    descending = sort.startswith("-")
    sort_field = SORTABLE_COLUMNS[sort.lstrip("-")][1]
    risks = risks.annotate(status_order=status_lifecycle_order())
    # Risk ID as a tie-breaker keeps the order stable, e.g. for equal scores.
    return risks.order_by(f"-{sort_field}" if descending else sort_field, "id")


def column_headings(query_params, current_sort):
    """
    Build the sortable column headings for the register table.

    Inputs: the current web address parameters and the current sort.
    Output: a list of dictionaries with each column's label, the address
    that sorts by it (keeping the current filters), and an arrow (▲/▼) on
    the column currently sorted. Clicking a sorted column reverses it.
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
