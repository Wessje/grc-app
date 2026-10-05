"""
Records the change history (audit trail) of risks.

Every save of a risk – from our own forms or the admin screen – goes through
`save_risk_with_history`, so no edit goes unrecorded. It compares the risk
before and after the save and writes one RiskChange row per changed field.
Archiving and restoring go through `archive_risk` and `restore_risk`, which
record an "Archived" or "Restored" event.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from risks.models import Risk, RiskChange

# Fields whose changes are recorded, in the order they appear on the form.
# The score is included so the audit trail shows its effect, even though it
# is calculated rather than typed in.
TRACKED_FIELDS = [
    "title",
    "description",
    "category",
    "owner",
    "risk_source",
    "date_identified",
    "inherent_likelihood",
    "inherent_impact",
    "inherent_score",
    "status",
    "response_type",
    "response_description",
    "accepted_by",
    "acceptance_date",
    "acceptance_expiry_date",
    "notes",
]


def display_value(risk, field_name):
    """
    Return a field's value as text, the way it is shown to people.

    Inputs: a risk and the field name. Output: text, e.g. "3 – Possible" for
    a scale, "In treatment" for a status, "5 Oct 2026" for a date, the
    category name for the category, and "" for an empty value.
    """
    field = Risk._meta.get_field(field_name)
    value = getattr(risk, field_name)
    if value in (None, ""):
        return ""
    if field.choices:
        return getattr(risk, f"get_{field_name}_display")()
    if field.get_internal_type() == "DateField":
        return date_format(value)
    return str(value)


def take_snapshot(risk):
    """
    Capture the current values of all tracked fields.

    Input: a risk. Output: a dictionary {field name: displayed value}.
    """
    return {field_name: display_value(risk, field_name) for field_name in TRACKED_FIELDS}


def field_label(field_name):
    """Return a field's human-readable label, e.g. "Inherent likelihood"."""
    label = Risk._meta.get_field(field_name).verbose_name
    return label[0].upper() + label[1:]


def save_risk_with_history(risk, user):
    """
    Save a risk and record what changed.

    Inputs: the risk (new or edited, already validated) and the logged-in
    user making the change.
    Output: nothing. A new risk gets one "Created" row; an edited risk gets
    one row per changed field (none if nothing changed). The save and its
    history are written together: either both succeed or neither does.
    """
    with transaction.atomic():
        if risk.pk is None:
            risk.save()
            RiskChange.objects.create(
                risk=risk, field_name="Created", new_value=risk.risk_id, changed_by=user
            )
            return

        # Read the stored version from the database: the `risk` object
        # passed in already holds the new values.
        before = take_snapshot(Risk.objects.get(pk=risk.pk))
        risk.save()
        after = take_snapshot(risk)
        for field_name in TRACKED_FIELDS:
            if before[field_name] != after[field_name]:
                RiskChange.objects.create(
                    risk=risk,
                    field_name=field_label(field_name),
                    old_value=before[field_name],
                    new_value=after[field_name],
                    changed_by=user,
                )


def archive_risk(risk, user):
    """
    Archive a risk (take it out of the register without deleting it).

    Inputs: the risk and the logged-in user. Output: nothing. Sets
    "Archived at" to now and records an "Archived" event. Does nothing if the
    risk is already archived, so the event is never recorded twice.
    """
    if risk.archived_at is not None:
        return
    with transaction.atomic():
        risk.archived_at = timezone.now()
        risk.save()
        RiskChange.objects.create(risk=risk, field_name="Archived", changed_by=user)


def restore_risk(risk, user):
    """
    Restore an archived risk to the register.

    Inputs: the risk and the logged-in user. Output: nothing. Clears
    "Archived at" and records a "Restored" event. Does nothing if the risk is
    not archived.
    """
    if risk.archived_at is None:
        return
    with transaction.atomic():
        risk.archived_at = None
        risk.save()
        RiskChange.objects.create(risk=risk, field_name="Restored", changed_by=user)
