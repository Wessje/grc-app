"""
Loads the starting risk categories and a set of made-up sample risks.

Run with: python manage.py load_sample_risks

All sample data is fictional – never put real organisational risks here.
Running the command again does not create duplicates: categories and risks
that already exist (matched by name/title) are left untouched, so any edits
you made to them are kept.
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from processes.models import Process
from risks.models import Risk, RiskCategory

STARTING_CATEGORIES = [
    "Cyber",
    "Operational",
    "Compliance",
    "Third party",
    "Strategic",
    "Financial",
]


def build_sample_risks(today):
    """
    Return the made-up sample risks as a list of dictionaries.

    Input: today's date. Acceptance dates are set relative to today, so the
    expired acceptance stays expired and the current one stays current no
    matter when the command is run.
    Output: one dictionary of field values per risk; "category" holds the
    category name. Together the risks cover every rating and every status.
    """
    days = datetime.timedelta
    return [
        {
            "title": "Phishing leads to stolen staff credentials",
            "description": "Staff enter their password on a fake login page sent by email.",
            "category": "Cyber",
            "owner": "IT security officer",
            "risk_source": "Email and Microsoft 365 login",
            "inherent_likelihood": 4,
            "inherent_impact": 4,  # 16 = High
            "status": Risk.Status.IN_TREATMENT,
            "response_type": Risk.ResponseType.MITIGATE,
            "response_description": "Roll out MFA to all staff and run quarterly phishing simulations.",
        },
        {
            "title": "Ransomware encrypts file servers",
            "description": "Malware encrypts shared drives, stopping work until data is restored.",
            "category": "Cyber",
            "owner": "IT manager",
            "risk_source": "Windows file servers",
            "inherent_likelihood": 3,
            "inherent_impact": 5,  # 15 = High
            "status": Risk.Status.MONITORING,
            "response_type": Risk.ResponseType.MITIGATE,
            "response_description": "Offline backups tested monthly; endpoint protection on all servers.",
        },
        {
            "title": "Unpatched internet-facing systems",
            "description": "Known vulnerabilities on public systems are not patched in time.",
            "category": "Cyber",
            "owner": "Infrastructure lead",
            "risk_source": "Customer portal and VPN gateway",
            "inherent_likelihood": 5,
            "inherent_impact": 4,  # 20 = Critical
            "status": Risk.Status.OPEN,
        },
        {
            "title": "Outage at cloud hosting provider",
            "description": "The hosting provider is unavailable for more than a working day.",
            "category": "Third party",
            "owner": "Head of IT",
            "risk_source": "Customer portal hosting",
            "inherent_likelihood": 2,
            "inherent_impact": 5,  # 10 = High
            "status": Risk.Status.MONITORING,
            "response_type": Risk.ResponseType.TRANSFER,
            "response_description": "Contractual SLA with service credits; business interruption insurance.",
        },
        {
            "title": "Data breach at payroll supplier",
            "description": "The payroll supplier leaks employee personal data.",
            "category": "Third party",
            "owner": "HR director",
            "risk_source": "Payroll outsourcing process",
            "inherent_likelihood": 3,
            "inherent_impact": 3,  # 9 = Medium
            "status": Risk.Status.OPEN,
        },
        {
            "title": "Legacy HR system out of vendor support",
            "description": "The HR system no longer receives security updates from the vendor.",
            "category": "Operational",
            "owner": "HR director",
            "risk_source": "HR system",
            "inherent_likelihood": 3,
            "inherent_impact": 2,  # 6 = Medium
            "status": Risk.Status.MONITORING,
            "response_type": Risk.ResponseType.ACCEPT,
            "response_description": "Accepted until the system is replaced; access limited to HR staff.",
            # Expired acceptance: due for re-review.
            "accepted_by": "Chief operating officer",
            "acceptance_date": today - days(400),
            "acceptance_expiry_date": today - days(35),
        },
        {
            "title": "Personal data breach not reported within 72 hours",
            "description": "A GDPR breach is not reported to the regulator in time.",
            "category": "Compliance",
            "owner": "Data protection officer",
            "risk_source": "Incident management process",
            "inherent_likelihood": 2,
            "inherent_impact": 4,  # 8 = Medium
            "status": Risk.Status.IN_TREATMENT,
            "response_type": Risk.ResponseType.MITIGATE,
            "response_description": "Write a breach-notification procedure and train the incident team.",
        },
        {
            "title": "Loss of key finance staff",
            "description": "Month-end closing depends on one person.",
            "category": "Operational",
            "owner": "Finance director",
            "risk_source": "Month-end closing process",
            "inherent_likelihood": 2,
            "inherent_impact": 2,  # 4 = Low
            "status": Risk.Status.OPEN,
        },
        {
            "title": "Scanned documents stored on office printer",
            "description": "The old printer kept copies of scanned documents on its hard disk.",
            "category": "Cyber",
            "owner": "Office manager",
            "risk_source": "Office printer",
            "inherent_likelihood": 1,
            "inherent_impact": 2,  # 2 = Low
            "status": Risk.Status.CLOSED,
            "response_type": Risk.ResponseType.AVOID,
            "response_description": "Printer replaced; old hard disk securely destroyed.",
        },
        {
            "title": "Delay entering a new regional market",
            "description": "Regulatory approval in the new region takes longer than planned.",
            "category": "Strategic",
            "owner": "Chief executive",
            "risk_source": "Expansion programme",
            "inherent_likelihood": 3,
            "inherent_impact": 3,  # 9 = Medium
            "status": Risk.Status.MONITORING,
            "response_type": Risk.ResponseType.ACCEPT,
            "response_description": "Delay is within the programme's tolerance.",
            # Current acceptance: still valid.
            "accepted_by": "Board",
            "acceptance_date": today - days(60),
            "acceptance_expiry_date": today + days(300),
        },
        {
            "title": "Currency swings reduce margins",
            "description": "Supplier costs in US dollars rise against the euro.",
            "category": "Financial",
            "owner": "Finance director",
            "risk_source": "Purchasing process",
            "inherent_likelihood": 4,
            "inherent_impact": 5,  # 20 = Critical
            "status": Risk.Status.IN_TREATMENT,
            "response_type": Risk.ResponseType.TRANSFER,
            "response_description": "Hedge expected dollar purchases with forward contracts.",
        },
    ]


class Command(BaseCommand):
    help = "Load the starting categories and made-up sample risks (safe to run again)."

    def handle(self, *args, **options):
        """
        Create any missing categories and sample risks, then report the counts.

        Everything is loaded in one transaction: if any sample risk fails
        validation, nothing is saved.
        """
        with transaction.atomic():
            categories_created = self.load_categories()
            risks_created, risks_skipped = self.load_risks()
        self.stdout.write(self.style.SUCCESS(
            f"Categories created: {categories_created}. "
            f"Risks created: {risks_created}. "
            f"Risks already present (left unchanged): {risks_skipped}."
        ))

    def load_categories(self):
        """Create any missing starting categories. Output: how many were created."""
        created_count = 0
        for name in STARTING_CATEGORIES:
            _, created = RiskCategory.objects.get_or_create(name=name)
            created_count += created
        return created_count

    def load_risks(self):
        """
        Create any sample risks that do not exist yet (matched by title).

        Each risk goes through the same validation as the admin screen, so the
        sample data always follows the register's rules.
        Output: (number created, number skipped because they already existed).
        """
        created_count = 0
        skipped_count = 0
        # Created only when a new sample risk needs it. Risks already in the
        # register are left as they are, including ones with no process yet.
        sample_process = None
        for fields in build_sample_risks(timezone.localdate()):
            if Risk.objects.filter(title=fields["title"]).exists():
                skipped_count += 1
                continue
            if sample_process is None:
                sample_process, _created = Process.objects.get_or_create(
                    name="Sample operations",
                    defaults={
                        "kind": Process.Kind.PROCESS,
                        "description": "Made-up process used by the sample risks.",
                        "owner": "Sample owner",
                    },
                )
            fields["category"] = RiskCategory.objects.get(name=fields["category"])
            fields["process"] = sample_process
            risk = Risk(**fields)
            risk.full_clean()
            risk.save()
            created_count += 1
        return created_count, skipped_count
