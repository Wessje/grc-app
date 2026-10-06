"""
Builds the 5×5 heat map shown on the register page: how many risks sit in
each likelihood × impact cell.

The heat map counts the same risks as the register table below it (after
filters), so the cell counts always add up to the number of risks shown.
"""

from collections import Counter

from risks.models import (
    IMPACT_CHOICES,
    LIKELIHOOD_CHOICES,
    calculate_inherent_score,
    rating_for_score,
)


def build_heat_map(risks):
    """
    Count risks per likelihood/impact cell and colour each cell by its rating.

    Input: the risks to count (e.g. the filtered register).
    Output: a dictionary with
      - "impact_labels": column headings, "1 – Insignificant" … "5 – Severe";
      - "rows": one row per likelihood, highest first (as on a printed heat
        map, where the top right is the worst corner). Each row has its
        "label" and five "cells", each with the "count" of risks and the
        "rating" of that cell's score (used for its colour).
    """
    counts = Counter((risk.inherent_likelihood, risk.inherent_impact) for risk in risks)
    rows = []
    for likelihood, likelihood_label in reversed(LIKELIHOOD_CHOICES):
        cells = []
        for impact, impact_label in IMPACT_CHOICES:
            score = calculate_inherent_score(likelihood, impact)
            cells.append({
                "count": counts[(likelihood, impact)],
                "rating": rating_for_score(score),
                "description": f"Likelihood {likelihood_label}, impact {impact_label}",
            })
        rows.append({"label": likelihood_label, "cells": cells})
    return {"impact_labels": [label for _, label in IMPACT_CHOICES], "rows": rows}
