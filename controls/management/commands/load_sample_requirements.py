"""
Loads a small starter set of framework requirements and maps some of them
to the sample controls.

Run with: python manage.py load_sample_requirements

The titles are our own short descriptions, not the text of ISO 27001, NIST CSF
or SOC 2. Running the command again does not create duplicates and does not
overwrite a title or a mapping you have edited. Mappings are only added when
the matching sample control already exists (load it with
`python manage.py load_sample_controls`).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from controls.models import Control, ControlRequirement, FrameworkRequirement

# (framework, reference, title). Titles are ours, not the wording of the standard.
SAMPLE_REQUIREMENTS = [
    (FrameworkRequirement.Framework.ISO_27001, "A.5.15",
     "Access is limited to people who need it"),
    (FrameworkRequirement.Framework.ISO_27001, "A.8.13",
     "Backup copies can be restored"),
    (FrameworkRequirement.Framework.NIST_CSF, "PR.AA-01",
     "People and systems prove who they are"),
    (FrameworkRequirement.Framework.NIST_CSF, "RC.RP-01",
     "Recovery is carried out after an incident"),
    (FrameworkRequirement.Framework.SOC_2, "CC6.1",
     "Access to systems is limited"),
    (FrameworkRequirement.Framework.SOC_2, "A1.2",
     "The service can be recovered after a disruption"),
]

# (control title, framework, reference). Skipped when that control is absent.
SAMPLE_MAPPINGS = [
    ("Multi-factor authentication", FrameworkRequirement.Framework.ISO_27001, "A.5.15"),
    ("Multi-factor authentication", FrameworkRequirement.Framework.NIST_CSF, "PR.AA-01"),
    ("Multi-factor authentication", FrameworkRequirement.Framework.SOC_2, "CC6.1"),
    ("Offline backups", FrameworkRequirement.Framework.ISO_27001, "A.8.13"),
    ("Offline backups", FrameworkRequirement.Framework.NIST_CSF, "RC.RP-01"),
    ("Offline backups", FrameworkRequirement.Framework.SOC_2, "A1.2"),
]


class Command(BaseCommand):
    help = "Load a starter set of framework requirements and map them to sample controls."

    def handle(self, *args, **options):
        """Create any missing requirements and mappings, then report the counts."""
        with transaction.atomic():
            requirements_created = self.load_requirements()
            mappings_created, mappings_skipped = self.load_mappings()
        self.stdout.write(self.style.SUCCESS(
            f"Requirements created: {requirements_created}. "
            f"Mappings created: {mappings_created}. "
            f"Mappings skipped (control missing or mapping already present): {mappings_skipped}."
        ))

    def load_requirements(self):
        """Create any missing requirements, matched by framework and reference."""
        created_count = 0
        for framework, reference, title in SAMPLE_REQUIREMENTS:
            if FrameworkRequirement.objects.filter(framework=framework, reference=reference).exists():
                continue
            requirement = FrameworkRequirement(
                framework=framework, reference=reference, title=title
            )
            requirement.full_clean()
            requirement.save()
            created_count += 1
        return created_count

    def load_mappings(self):
        """
        Map sample controls to sample requirements, matched by title and reference.

        An existing mapping is left in place. Output: (number created, number skipped).
        """
        created_count = 0
        skipped_count = 0
        for control_title, framework, reference in SAMPLE_MAPPINGS:
            control = Control.objects.filter(title=control_title).first()
            requirement = FrameworkRequirement.objects.get(framework=framework, reference=reference)
            if control is None or ControlRequirement.objects.filter(
                control=control, requirement=requirement
            ).exists():
                skipped_count += 1
                continue
            mapping = ControlRequirement(control=control, requirement=requirement)
            mapping.full_clean()
            mapping.save()
            created_count += 1
        return created_count, skipped_count
