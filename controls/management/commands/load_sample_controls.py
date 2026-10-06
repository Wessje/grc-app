"""
Loads made-up sample controls and links some of them to the sample risks.

Run with: python manage.py load_sample_controls

All sample data is fictional. Running the command again does not create
duplicates and does not overwrite controls or links you have edited.
Links are only added when the matching sample risk already exists
(load it with `python manage.py load_sample_risks`).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from controls.models import Control, RiskControl
from risks.models import Risk

# (title, description, owner, type, status)
SAMPLE_CONTROLS = [
    (
        "Multi-factor authentication",
        "Staff must use a second factor when signing in to email and the customer portal.",
        "IT security officer",
        Control.ControlType.PREVENTIVE,
        Control.Status.IN_PLACE,
    ),
    (
        "Offline backups",
        "File servers are backed up nightly to storage that is not connected to the network.",
        "IT manager",
        Control.ControlType.CORRECTIVE,
        Control.Status.IN_PLACE,
    ),
    (
        "Quarterly access review",
        "Managers confirm, every quarter, who still needs access to each system.",
        "IT security officer",
        Control.ControlType.DETECTIVE,
        Control.Status.IN_PLACE,
    ),
    (
        "Breach notification procedure",
        "A written procedure for reporting a personal-data breach to the regulator within 72 hours.",
        "Data protection officer",
        Control.ControlType.CORRECTIVE,
        Control.Status.PLANNED,
    ),
    (
        "Security awareness training",
        "Yearly training on phishing and how to report a suspicious email.",
        "HR director",
        Control.ControlType.PREVENTIVE,
        Control.Status.NOT_OPERATING,
    ),
    (
        "Vulnerability scanning",
        "Monthly scans of internet-facing systems, with critical findings patched within a week.",
        "Infrastructure lead",
        Control.ControlType.DETECTIVE,
        Control.Status.PLANNED,
    ),
]

# (control title, risk title, effectiveness). Skipped when that risk is absent.
SAMPLE_LINKS = [
    ("Multi-factor authentication", "Phishing leads to stolen staff credentials",
     RiskControl.Effectiveness.EFFECTIVE),
    ("Security awareness training", "Phishing leads to stolen staff credentials",
     RiskControl.Effectiveness.PARTIAL),
    ("Offline backups", "Ransomware encrypts file servers",
     RiskControl.Effectiveness.EFFECTIVE),
    ("Vulnerability scanning", "Unpatched internet-facing systems",
     RiskControl.Effectiveness.PARTIAL),
    ("Quarterly access review", "Data breach at payroll supplier",
     RiskControl.Effectiveness.PARTIAL),
    ("Breach notification procedure", "Personal data breach not reported within 72 hours",
     RiskControl.Effectiveness.INEFFECTIVE),
]


class Command(BaseCommand):
    help = "Load made-up sample controls and link them to sample risks (safe to run again)."

    def handle(self, *args, **options):
        """Create any missing controls and links, then report the counts."""
        with transaction.atomic():
            controls_created = self.load_controls()
            links_created, links_skipped = self.load_links()
        self.stdout.write(self.style.SUCCESS(
            f"Controls created: {controls_created}. "
            f"Links created: {links_created}. "
            f"Links skipped (risk missing or link already present): {links_skipped}."
        ))

    def load_controls(self):
        """Create any missing sample controls, matched by title. Output: how many were created."""
        created_count = 0
        for title, description, owner, control_type, status in SAMPLE_CONTROLS:
            if Control.objects.filter(title=title).exists():
                continue
            control = Control(
                title=title, description=description, owner=owner,
                control_type=control_type, status=status,
            )
            control.full_clean()
            control.save()
            created_count += 1
        return created_count

    def load_links(self):
        """
        Link sample controls to sample risks, matched by title.

        An existing link is left unchanged, so an effectiveness you edited
        is kept. Output: (number created, number skipped).
        """
        created_count = 0
        skipped_count = 0
        for control_title, risk_title, effectiveness in SAMPLE_LINKS:
            control = Control.objects.get(title=control_title)
            risk = Risk.objects.filter(title=risk_title).first()
            if risk is None or RiskControl.objects.filter(risk=risk, control=control).exists():
                skipped_count += 1
                continue
            link = RiskControl(risk=risk, control=control, effectiveness=effectiveness)
            link.full_clean()
            link.save()
            created_count += 1
        return created_count, skipped_count
