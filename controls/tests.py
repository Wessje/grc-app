"""
Automated checks for the control register: Control IDs, required fields
and the admin screen.

Run with: python manage.py test
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from controls.models import Control


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
