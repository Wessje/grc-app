"""
Records changes to the controls linked to a risk.

Used by the risk form and the admin screen, so a control added, removed or
re-rated is in the risk's change history either way.
"""

from risks.models import RiskChange


def snapshot_control_links(risk):
    """
    Capture the controls currently linked to a risk.

    Input: a saved risk. Output: a dictionary {control record number:
    (label, effectiveness)}, e.g. {3: ("CTRL-0001 Multi-factor authentication",
    "Effective")}.
    """
    if risk.pk is None:
        return {}
    return {
        link.control_id: (
            f"{link.control.control_id} {link.control.title}",
            link.get_effectiveness_display(),
        )
        for link in risk.control_links.select_related("control")
    }


def record_control_link_changes(risk, before, after, user):
    """
    Write one history row for each control link that changed.

    Inputs: the risk, the snapshots from before and after the save (see
    `snapshot_control_links`), and the logged-in user. Output: nothing.
    An added control has an empty old value; a removed one has an empty new
    value; a re-rated one shows the old and new effectiveness.
    """
    for control_pk in set(before) | set(after):
        old = before.get(control_pk)
        new = after.get(control_pk)
        if old == new:
            continue
        label = (new or old)[0]
        RiskChange.objects.create(
            risk=risk,
            field_name=f"Control: {label}"[:100],
            old_value="" if old is None else old[1],
            new_value="" if new is None else new[1],
            changed_by=user,
        )
