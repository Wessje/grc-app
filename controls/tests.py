"""
Automated checks for the control register: Control IDs, required fields
and the admin screen.

Run with: python manage.py test
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from controls.forms import RiskControlLinkForm
from controls.models import Control, ControlRequirement, FrameworkRequirement, RiskControl
from risks.models import Risk, RiskCategory, RiskChange


def make_control(**overrides):
    """
    Build a valid, unsaved control for tests.

    Input: any fields to change from the defaults.
    Output: a Control object (not yet saved to the database).
    """
    fields = {
        "title": "Multi-factor authentication",
        "description": "Made-up test control.",
        "owner": "IT security officer",
        "control_type": Control.ControlType.PREVENTIVE,
    }
    fields.update(overrides)
    return Control(**fields)


def validation_errors(control):
    """Run all validation on a control and return the {field: messages} errors."""
    try:
        control.full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


class ControlTests(TestCase):
    """Control IDs, defaults and required fields."""

    def test_valid_control_passes(self):
        self.assertEqual(validation_errors(make_control()), {})

    def test_new_control_defaults_to_planned(self):
        self.assertEqual(make_control().status, Control.Status.PLANNED)

    def test_required_fields(self):
        control = make_control(title="", description="", owner="", control_type="")
        errors = validation_errors(control)
        for field in ["title", "description", "owner", "control_type"]:
            self.assertIn(field, errors)

    def test_unknown_type_and_status_are_rejected(self):
        control = make_control(control_type="compensating", status="retired")
        errors = validation_errors(control)
        self.assertIn("control_type", errors)
        self.assertIn("status", errors)

    def test_ids_are_generated_in_sequence_and_do_not_change(self):
        first = make_control()
        first.save()
        second = make_control(title="Backups")
        second.save()
        self.assertRegex(first.control_id, r"^CTRL-\d{4}$")
        self.assertEqual(int(second.control_id[5:]), int(first.control_id[5:]) + 1)

        original_id = first.control_id
        first.title = "New title"
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.control_id, original_id)


class ControlAdminTests(TestCase):
    """The admin screen protects Control IDs and archived controls."""

    def setUp(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(admin_user)

    def admin_form_data(self, **overrides):
        """Return valid form data for the admin's add/change control page."""
        data = {
            "title": "Backups",
            "description": "Made-up test control.",
            "owner": "IT manager",
            "control_type": Control.ControlType.CORRECTIVE,
            "status": Control.Status.IN_PLACE,
            "notes": "",
            "requirement_links-TOTAL_FORMS": "0",
            "requirement_links-INITIAL_FORMS": "0",
            "requirement_links-MIN_NUM_FORMS": "0",
            "requirement_links-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_add_control_generates_id(self):
        response = self.client.post(reverse("admin:controls_control_add"), self.admin_form_data())
        self.assertEqual(response.status_code, 302)
        control = Control.objects.get()
        self.assertTrue(control.control_id.startswith("CTRL-"))
        self.assertEqual(control.status, Control.Status.IN_PLACE)

    def test_admin_rejects_a_control_without_a_type(self):
        response = self.client.post(
            reverse("admin:controls_control_add"), self.admin_form_data(control_type="")
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(Control.objects.exists())

    def test_archived_control_cannot_be_edited_in_admin(self):
        control = make_control(archived_at=timezone.now())
        control.save()
        change_url = reverse("admin:controls_control_change", args=[control.pk])

        page = self.client.get(change_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="_save"')

        response = self.client.post(change_url, self.admin_form_data(title="Changed"))
        self.assertEqual(response.status_code, 403)
        control.refresh_from_db()
        self.assertEqual(control.title, "Multi-factor authentication")

    def test_controls_cannot_be_deleted_in_admin(self):
        control = make_control()
        control.save()
        response = self.client.post(reverse("admin:controls_control_delete", args=[control.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Control.objects.filter(pk=control.pk).exists())


def make_risk_for_links():
    """Create and save one risk that control links can point at. Output: the risk."""
    category = RiskCategory.objects.create(name="Cyber")
    risk = Risk(
        title="Phishing leads to stolen staff credentials",
        description="Made-up test risk.",
        category=category,
        owner="IT security officer",
        risk_source="Email",
        inherent_likelihood=4,
        inherent_impact=4,
    )
    risk.save()
    return risk


class RiskControlLinkTests(TestCase):
    """A control can address a risk, once, with an effectiveness rating."""

    def setUp(self):
        self.risk = make_risk_for_links()
        self.control = make_control()
        self.control.save()
        self.other = make_control(title="Offline backups", control_type=Control.ControlType.CORRECTIVE)
        self.other.save()

    def test_link_is_saved_with_its_effectiveness(self):
        link = RiskControl(
            risk=self.risk, control=self.control,
            effectiveness=RiskControl.Effectiveness.EFFECTIVE,
        )
        link.full_clean()
        link.save()
        self.assertEqual(self.risk.control_links.get().effectiveness, "effective")

    def test_same_control_cannot_be_linked_twice(self):
        RiskControl.objects.create(
            risk=self.risk, control=self.control,
            effectiveness=RiskControl.Effectiveness.EFFECTIVE,
        )
        duplicate = RiskControl(
            risk=self.risk, control=self.control,
            effectiveness=RiskControl.Effectiveness.PARTIAL,
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save()

    def test_linked_risk_and_control_cannot_be_deleted(self):
        RiskControl.objects.create(
            risk=self.risk, control=self.control,
            effectiveness=RiskControl.Effectiveness.PARTIAL,
        )
        with self.assertRaises(ProtectedError):
            self.risk.delete()
        with self.assertRaises(ProtectedError):
            self.control.delete()


class ControlLinkFormTests(TestCase):
    """The risk form saves control links and records them in the history."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.risk = make_risk_for_links()
        self.control = make_control()
        self.control.save()

    def edit_data(self, **overrides):
        """Return a valid edit-form submission, plus any control-link fields."""
        data = {
            "title": self.risk.title,
            "description": self.risk.description,
            "category": self.risk.category_id,
            "owner": self.risk.owner,
            "risk_source": self.risk.risk_source,
            "date_identified": self.risk.date_identified.isoformat(),
            "inherent_likelihood": 4,
            "inherent_impact": 4,
            "status": self.risk.status,
            "control_links-TOTAL_FORMS": "1",
            "control_links-INITIAL_FORMS": "0",
            "control_links-MIN_NUM_FORMS": "0",
            "control_links-MAX_NUM_FORMS": "1000",
            "control_links-0-id": "",
            "control_links-0-control": "",
            "control_links-0-effectiveness": "",
        }
        data.update(overrides)
        return data

    def test_linking_a_control_shows_it_and_records_history(self):
        response = self.client.post(
            reverse("risks:risk_edit", args=[self.risk.pk]),
            self.edit_data(**{
                "control_links-0-control": self.control.pk,
                "control_links-0-effectiveness": RiskControl.Effectiveness.EFFECTIVE,
            }),
        )
        self.assertRedirects(response, reverse("risks:risk_detail", args=[self.risk.pk]))
        link = self.risk.control_links.get()
        self.assertEqual(link.effectiveness, RiskControl.Effectiveness.EFFECTIVE)

        page = self.client.get(reverse("risks:risk_detail", args=[self.risk.pk]))
        self.assertContains(page, self.control.control_id)
        self.assertContains(page, "Effective")
        change = RiskChange.objects.get(risk=self.risk)
        self.assertIn(self.control.control_id, change.field_name)
        self.assertEqual(change.old_value, "")
        self.assertEqual(change.new_value, "Effective")
        self.assertEqual(change.changed_by, self.user)

    def test_control_without_effectiveness_is_rejected(self):
        response = self.client.post(
            reverse("risks:risk_edit", args=[self.risk.pk]),
            self.edit_data(**{"control_links-0-control": self.control.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Record how effective this control is")
        self.assertFalse(self.risk.control_links.exists())

    def test_duplicate_rows_are_rejected(self):
        data = self.edit_data()
        data.update({
            "control_links-TOTAL_FORMS": "2",
            "control_links-1-id": "",
            "control_links-1-control": self.control.pk,
            "control_links-1-effectiveness": RiskControl.Effectiveness.PARTIAL,
            "control_links-0-control": self.control.pk,
            "control_links-0-effectiveness": RiskControl.Effectiveness.EFFECTIVE,
        })
        response = self.client.post(reverse("risks:risk_edit", args=[self.risk.pk]), data)
        self.assertContains(response, "Please correct the duplicate data for control.")
        self.assertFalse(self.risk.control_links.exists())

    def test_blank_spare_row_is_ignored(self):
        response = self.client.post(
            reverse("risks:risk_edit", args=[self.risk.pk]), self.edit_data()
        )
        self.assertRedirects(response, reverse("risks:risk_detail", args=[self.risk.pk]))
        self.assertFalse(self.risk.control_links.exists())
        self.assertFalse(RiskChange.objects.filter(risk=self.risk).exists())


class SampleControlTests(TestCase):
    """load_sample_controls covers every type and status, and is safe to repeat."""

    def test_loads_controls_and_links_without_duplicates(self):
        call_command("load_sample_risks")
        call_command("load_sample_controls")
        self.assertEqual(set(Control.objects.values_list("control_type", flat=True)),
                         set(Control.ControlType.values))
        self.assertEqual(set(Control.objects.values_list("status", flat=True)),
                         set(Control.Status.values))
        self.assertEqual(
            set(RiskControl.objects.values_list("effectiveness", flat=True)),
            set(RiskControl.Effectiveness.values),
        )
        phishing = Risk.objects.get(title="Phishing leads to stolen staff credentials")
        self.assertEqual(phishing.control_links.count(), 2)

        control_count = Control.objects.count()
        link_count = RiskControl.objects.count()
        call_command("load_sample_controls")
        self.assertEqual(Control.objects.count(), control_count)
        self.assertEqual(RiskControl.objects.count(), link_count)


class ControlPageTests(TestCase):
    """The control list and detail pages."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        call_command("load_sample_risks")
        call_command("load_sample_controls")
        self.control = Control.objects.get(title="Multi-factor authentication")

    def test_logged_out_visitors_are_sent_to_login(self):
        self.client.logout()
        for url in [
            reverse("controls:control_list"),
            reverse("controls:control_detail", args=[self.control.pk]),
        ]:
            with self.subTest(url):
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_list_shows_active_controls_and_risk_counts(self):
        archived = make_control(title="Old control", archived_at=timezone.now())
        archived.save()
        response = self.client.get(reverse("controls:control_list"))
        self.assertContains(response, self.control.control_id)
        self.assertContains(response, "Multi-factor authentication")
        self.assertContains(response, "Preventive")
        self.assertContains(response, "In place")
        self.assertNotContains(response, "Old control")
        shown = {control.title: control.risk_count for control in response.context["controls"]}
        self.assertEqual(shown["Multi-factor authentication"], 1)
        self.assertEqual(shown["Security awareness training"], 1)
        self.assertNotIn("Old control", shown)

    def test_detail_shows_the_control_and_the_risks_it_addresses(self):
        response = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(response, self.control.control_id)
        self.assertContains(response, self.control.description)
        self.assertContains(response, "IT security officer")
        self.assertContains(response, "Phishing leads to stolen staff credentials")
        self.assertContains(response, "Effective")
        self.assertContains(response, "High")

    def test_risk_page_links_to_the_control(self):
        risk = Risk.objects.get(title="Phishing leads to stolen staff credentials")
        response = self.client.get(reverse("risks:risk_detail", args=[risk.pk]))
        detail_url = reverse("controls:control_detail", args=[self.control.pk])
        self.assertContains(response, f'href="{detail_url}"')

    def test_unknown_control_is_not_found(self):
        response = self.client.get(reverse("controls:control_detail", args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_archived_control_can_still_be_opened(self):
        self.control.archived_at = timezone.now()
        self.control.save()
        response = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(response, "read-only until it is restored")
        self.assertNotContains(response, ">Edit</a>")


def control_form_data(**overrides):
    """
    Build a valid submission for the New control and Edit pages.

    Input: any fields to change from the defaults.
    Output: a dictionary the test client can post.
    """
    data = {
        "title": "Visitor sign-in log",
        "description": "Visitors sign in at reception.",
        "owner": "Facilities",
        "control_type": Control.ControlType.DETECTIVE,
        "status": Control.Status.PLANNED,
        "notes": "",
    }
    data.update(overrides)
    return data


class ControlFormPagesTests(TestCase):
    """The New and Edit pages validate input and assign a Control ID."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)

    def test_empty_form_is_rejected_with_messages(self):
        response = self.client.post(reverse("controls:control_create"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(response, "This field is required.")
        self.assertFalse(Control.objects.exists())

    def test_create_assigns_a_control_id_and_opens_the_detail_page(self):
        response = self.client.post(
            reverse("controls:control_create"), control_form_data(), follow=True
        )
        control = Control.objects.get()
        self.assertRedirects(response, reverse("controls:control_detail", args=[control.pk]))
        self.assertEqual(control.control_id, "CTRL-0001")
        self.assertEqual(control.status, Control.Status.PLANNED)
        self.assertContains(response, "CTRL-0001 created.")
        self.assertContains(response, "Visitor sign-in log")

    def test_edit_saves_the_change(self):
        self.client.post(reverse("controls:control_create"), control_form_data())
        control = Control.objects.get()
        response = self.client.post(
            reverse("controls:control_edit", args=[control.pk]),
            control_form_data(status=Control.Status.IN_PLACE, owner="Reception"),
        )
        self.assertRedirects(response, reverse("controls:control_detail", args=[control.pk]))
        control.refresh_from_db()
        self.assertEqual(control.status, Control.Status.IN_PLACE)
        self.assertEqual(control.owner, "Reception")
        self.assertEqual(control.control_id, "CTRL-0001")

    def test_archived_control_cannot_be_edited(self):
        control = make_control(archived_at=timezone.now())
        control.save()
        edit_url = reverse("controls:control_edit", args=[control.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        response = self.client.post(edit_url, control_form_data(title="Changed"))
        self.assertEqual(response.status_code, 403)
        control.refresh_from_db()
        self.assertEqual(control.title, "Multi-factor authentication")

    def test_users_without_permission_cannot_create_or_edit(self):
        control = make_control()
        control.save()
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("controls:control_create")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("controls:control_edit", args=[control.pk])).status_code, 403
        )
        detail = self.client.get(reverse("controls:control_detail", args=[control.pk]))
        self.assertNotContains(detail, ">Edit</a>")
        listing = self.client.get(reverse("controls:control_list"))
        self.assertNotContains(listing, "New control")


class FrameworkPageTests(TestCase):
    """Framework mappings on the control page, and the framework filter on the list."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        call_command("load_sample_risks")
        call_command("load_sample_controls")
        call_command("load_sample_requirements")
        self.mfa = Control.objects.get(title="Multi-factor authentication")

    def titles(self, **params):
        """Open the control list with the given filter. Output: the titles shown."""
        response = self.client.get(reverse("controls:control_list"), params)
        self.assertEqual(response.status_code, 200)
        return [control.title for control in response.context["controls"]]

    def test_detail_lists_mapped_requirements(self):
        response = self.client.get(reverse("controls:control_detail", args=[self.mfa.pk]))
        self.assertContains(response, "ISO 27001")
        self.assertContains(response, "A.5.15")
        self.assertContains(response, "Access is limited to people who need it")
        self.assertContains(response, "PR.AA-01")
        self.assertContains(response, "CC6.1")

    def test_unmapped_control_says_so(self):
        spare = make_control(title="Unmapped control")
        spare.save()
        response = self.client.get(reverse("controls:control_detail", args=[spare.pk]))
        self.assertContains(response, "Not mapped to a framework requirement yet")

    def test_framework_filter(self):
        iso = self.titles(framework="iso_27001")
        self.assertIn("Multi-factor authentication", iso)
        self.assertIn("Offline backups", iso)
        self.assertNotIn("Quarterly access review", iso)

        self.assertEqual(self.titles(framework="nonsense"), self.titles())

    def test_filter_does_not_inflate_the_risk_count(self):
        response = self.client.get(reverse("controls:control_list"), {"framework": "iso_27001"})
        mfa = next(control for control in response.context["controls"] if control.pk == self.mfa.pk)
        self.assertEqual(mfa.risk_count, 1)


class FrameworkRequirementTests(TestCase):
    """Catalogue references are unique within one framework, and mappings are one-to-one."""

    def setUp(self):
        self.iso = FrameworkRequirement.objects.create(
            framework=FrameworkRequirement.Framework.ISO_27001,
            reference="A.5.15",
            title="Access is limited to people who need it",
        )
        self.control = make_control()
        self.control.save()

    def test_same_reference_is_allowed_in_another_framework(self):
        other = FrameworkRequirement(
            framework=FrameworkRequirement.Framework.NIST_CSF,
            reference="A.5.15",
            title="A different catalogue.",
        )
        other.full_clean()
        other.save()

    def test_duplicate_reference_in_one_framework_is_rejected(self):
        duplicate = FrameworkRequirement(
            framework=FrameworkRequirement.Framework.ISO_27001,
            reference="A.5.15",
            title="Another title",
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save()

    def test_mapping_is_unique_and_blocks_deletion(self):
        ControlRequirement.objects.create(control=self.control, requirement=self.iso)
        duplicate = ControlRequirement(control=self.control, requirement=self.iso)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(ProtectedError):
            self.iso.delete()
        with self.assertRaises(ProtectedError):
            self.control.delete()

    def test_sample_requirements_cover_every_framework_and_can_be_rerun(self):
        call_command("load_sample_controls")
        call_command("load_sample_requirements")
        frameworks = set(FrameworkRequirement.objects.values_list("framework", flat=True))
        self.assertEqual(frameworks, set(FrameworkRequirement.Framework.values))
        mfa = Control.objects.get(title="Multi-factor authentication")
        self.assertEqual(mfa.requirement_links.count(), 3)

        requirement_count = FrameworkRequirement.objects.count()
        mapping_count = ControlRequirement.objects.count()
        call_command("load_sample_requirements")
        self.assertEqual(FrameworkRequirement.objects.count(), requirement_count)
        self.assertEqual(ControlRequirement.objects.count(), mapping_count)

    def test_admin_can_add_a_requirement_and_map_it(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(admin_user)
        response = self.client.post(reverse("admin:controls_frameworkrequirement_add"), {
            "framework": FrameworkRequirement.Framework.SOC_2,
            "reference": "CC6.1",
            "title": "Access to systems is limited",
        })
        self.assertEqual(response.status_code, 302)
        requirement = FrameworkRequirement.objects.get(reference="CC6.1")

        change_url = reverse("admin:controls_control_change", args=[self.control.pk])
        response = self.client.post(change_url, {
            "title": self.control.title,
            "description": self.control.description,
            "owner": self.control.owner,
            "control_type": self.control.control_type,
            "status": self.control.status,
            "notes": "",
            "requirement_links-TOTAL_FORMS": "1",
            "requirement_links-INITIAL_FORMS": "0",
            "requirement_links-MIN_NUM_FORMS": "0",
            "requirement_links-MAX_NUM_FORMS": "1000",
            "requirement_links-0-id": "",
            "requirement_links-0-requirement": requirement.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.control.requirement_links.get().requirement, requirement)


class ControlArchiveTests(TestCase):
    """Archiving hides a control from the register; restoring brings it back."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        call_command("load_sample_risks")
        self.control = make_control(title="Control to archive", status=Control.Status.IN_PLACE)
        self.control.save()
        self.risk = Risk.objects.get(title="Phishing leads to stolen staff credentials")
        RiskControl.objects.create(
            risk=self.risk,
            control=self.control,
            effectiveness=RiskControl.Effectiveness.EFFECTIVE,
        )
        self.archive_url = reverse("controls:control_archive", args=[self.control.pk])
        self.restore_url = reverse("controls:control_restore", args=[self.control.pk])

    def test_confirmation_page_does_not_archive_yet(self):
        response = self.client.get(self.archive_url)
        self.assertContains(response, "Archive control")
        self.assertContains(response, "not deleted")
        self.control.refresh_from_db()
        self.assertIsNone(self.control.archived_at)

    def test_archive_hides_from_register_and_keeps_the_link(self):
        self.assertContains(self.client.get(reverse("controls:control_list")), "Control to archive")
        response = self.client.post(self.archive_url)
        self.assertRedirects(response, reverse("controls:control_list"))
        self.control.refresh_from_db()
        self.assertIsNotNone(self.control.archived_at)
        self.assertEqual(self.control.status, Control.Status.IN_PLACE)
        self.assertEqual(self.control.risk_links.count(), 1)
        self.assertNotContains(self.client.get(reverse("controls:control_list")), "Control to archive")
        self.assertContains(
            self.client.get(reverse("controls:archived_control_list")), "Control to archive"
        )
        risk_page = self.client.get(reverse("risks:risk_detail", args=[self.risk.pk]))
        self.assertContains(risk_page, "Control to archive")
        self.assertContains(risk_page, "Archived")

    def test_restore_brings_the_control_back(self):
        self.client.post(self.archive_url)
        response = self.client.post(self.restore_url, follow=True)
        self.assertRedirects(response, reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(response, "restored to the register")
        self.control.refresh_from_db()
        self.assertIsNone(self.control.archived_at)
        self.assertNotContains(
            self.client.get(reverse("controls:archived_control_list")), "Control to archive"
        )
        self.assertContains(self.client.get(reverse("controls:control_list")), "Control to archive")

    def test_archived_detail_shows_restore_not_edit(self):
        self.client.post(self.archive_url)
        response = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(response, "read-only until it is restored")
        self.assertContains(response, ">Restore</button>")
        self.assertNotContains(response, ">Edit</a>")
        self.assertContains(response, "Back to archived controls")

    def test_restore_only_accepts_form_submissions(self):
        self.client.post(self.archive_url)
        self.assertEqual(self.client.get(self.restore_url).status_code, 405)
        self.control.refresh_from_db()
        self.assertIsNotNone(self.control.archived_at)

    def test_users_without_permission_cannot_archive_or_restore(self):
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.archive_url).status_code, 403)
        self.control.refresh_from_db()
        self.assertIsNone(self.control.archived_at)

        self.client.force_login(self.user)
        self.client.post(self.archive_url)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.restore_url).status_code, 403)
        archive_page = self.client.get(reverse("controls:archived_control_list"))
        self.assertContains(archive_page, "Control to archive")
        self.assertNotContains(archive_page, ">Restore</button>")

    def test_risk_form_cannot_newly_link_an_archived_control(self):
        self.client.post(self.archive_url)
        self.control.refresh_from_db()
        self.assertNotIn(self.control, RiskControlLinkForm().fields["control"].queryset)
        existing = RiskControlLinkForm(instance=self.control.risk_links.get())
        self.assertIn(self.control, existing.fields["control"].queryset)
