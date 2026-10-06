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

from controls.models import Control, RiskControl
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
