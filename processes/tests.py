"""
Automated checks for processes and solutions: IDs, the pages, and archive.

Run with: python manage.py test
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from controls.models import Control
from processes.models import Process, ProcessControl


def make_process(**overrides):
    """
    Build a valid, unsaved process for tests.

    Input: any fields to change from the defaults.
    Output: a Process object (not yet saved to the database).
    """
    fields = {
        "kind": Process.Kind.PROCESS,
        "name": "Payroll",
        "description": "Paying staff each month.",
        "owner": "Finance",
    }
    fields.update(overrides)
    return Process(**fields)


def validation_errors(process):
    """Run all validation on a process and return the {field: messages} errors."""
    try:
        process.full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


def form_data(**overrides):
    """
    Build a valid submission for the New and Edit pages.

    Input: any fields to change from the defaults.
    Output: a dictionary the test client can post.
    """
    data = {
        "kind": Process.Kind.SOLUTION,
        "name": "Email",
        "description": "Staff email and calendars.",
        "owner": "IT manager",
        "notes": "",
        # No controls in scope. The link rows still have to be present.
        "control_links-TOTAL_FORMS": "0",
        "control_links-INITIAL_FORMS": "0",
        "control_links-MIN_NUM_FORMS": "0",
        "control_links-MAX_NUM_FORMS": "1000",
    }
    data.update(overrides)
    return data


class ProcessTests(TestCase):
    """IDs, required fields and the admin screen."""

    def test_valid_process_passes(self):
        self.assertEqual(validation_errors(make_process()), {})

    def test_required_fields(self):
        errors = validation_errors(make_process(kind="", name="", description="", owner=""))
        for field in ["kind", "name", "description", "owner"]:
            self.assertIn(field, errors)

    def test_id_is_assigned_once_and_shared_by_processes_and_solutions(self):
        first = make_process()
        first.save()
        second = make_process(kind=Process.Kind.SOLUTION, name="Email")
        second.save()
        self.assertEqual(first.process_id, "PROC-0001")
        self.assertEqual(second.process_id, "PROC-0002")
        first.name = "Payroll run"
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.process_id, "PROC-0001")

    def test_admin_add_generates_an_id_and_delete_is_refused(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(admin_user)
        response = self.client.post(reverse("admin:processes_process_add"), form_data())
        self.assertEqual(response.status_code, 302)
        process = Process.objects.get()
        self.assertEqual(process.process_id, "PROC-0001")

        response = self.client.post(reverse("admin:processes_process_delete", args=[process.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Process.objects.filter(pk=process.pk).exists())


class ProcessPageTests(TestCase):
    """The list, the form, and archive."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)

    def test_create_shows_on_the_list_and_the_detail_page(self):
        response = self.client.post(reverse("processes:process_create"), form_data(), follow=True)
        process = Process.objects.get()
        self.assertRedirects(response, reverse("processes:process_detail", args=[process.pk]))
        self.assertContains(response, "PROC-0001 created.")
        self.assertContains(response, "Staff email and calendars.")
        listing = self.client.get(reverse("processes:process_list"))
        self.assertContains(listing, "Email")
        self.assertContains(listing, "Solution")

    def test_empty_form_is_rejected(self):
        response = self.client.post(reverse("processes:process_create"), {})
        self.assertContains(response, "Please correct the errors below.")
        self.assertFalse(Process.objects.exists())

    def test_readers_cannot_create_or_edit(self):
        process = make_process()
        process.save()
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("processes:process_create")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("processes:process_edit", args=[process.pk])).status_code, 403
        )
        self.assertNotContains(self.client.get(reverse("processes:process_list")), ">New process or solution</a>")

    def test_archive_hides_it_and_restore_brings_it_back(self):
        process = make_process(name="Email")
        process.save()
        archive_url = reverse("processes:process_archive", args=[process.pk])
        self.client.get(archive_url)
        process.refresh_from_db()
        self.assertIsNone(process.archived_at)

        self.client.post(archive_url)
        process.refresh_from_db()
        self.assertIsNotNone(process.archived_at)
        self.assertNotContains(self.client.get(reverse("processes:process_list")), "Email")
        self.assertContains(self.client.get(reverse("processes:archived_process_list")), "Email")

        self.client.post(reverse("processes:process_restore", args=[process.pk]))
        process.refresh_from_db()
        self.assertIsNone(process.archived_at)
        self.assertEqual(self.client.get(reverse("processes:process_edit", args=[process.pk])).status_code, 200)

    def test_type_filter_search_and_sort(self):
        email = make_process(name="Email", kind=Process.Kind.SOLUTION, description="Staff email.")
        email.save()
        payroll = make_process(name="Payroll", description="Paying staff each month.")
        payroll.save()

        solutions = self.client.get(reverse("processes:process_list"), {"kind": "solution"})
        self.assertContains(solutions, "Email")
        self.assertNotContains(solutions, "Payroll")

        found = self.client.get(reverse("processes:process_list"), {"q": "Paying staff"})
        self.assertContains(found, "Payroll")
        self.assertNotContains(found, "Email")

        unknown = self.client.get(reverse("processes:process_list"), {"kind": "nope"})
        self.assertContains(unknown, "Email")
        self.assertContains(unknown, "Payroll")

        by_name = self.client.get(reverse("processes:process_list"), {"sort": "name"})
        content = by_name.content.decode()
        self.assertLess(content.index(">Email<"), content.index(">Payroll<"))

    def test_archive_pages_switch_between_every_module(self):
        page = self.client.get(reverse("processes:archived_process_list"))
        self.assertContains(page, 'aria-label="Archives"')
        self.assertContains(
            page,
            f'href="{reverse("processes:archived_process_list")}" class="current"',
        )
        self.assertContains(page, reverse("risks:archived_risk_list"))
        self.assertContains(page, reverse("controls:archived_control_list"))
        self.assertContains(page, reverse("assessments:archived_assessment_list"))
        listing = self.client.get(reverse("processes:process_list"))
        self.assertContains(listing, "<summary>Archive</summary>")
        self.assertContains(listing, reverse("assessments:archived_assessment_list"))

    def test_archived_record_cannot_be_edited(self):
        process = make_process(archived_at=timezone.now())
        process.save()
        edit_url = reverse("processes:process_edit", args=[process.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        self.assertEqual(self.client.get(reverse("processes:process_restore", args=[process.pk])).status_code, 405)


def make_control(**overrides):
    """Build and save one control. Input: any fields to change. Output: the control."""
    fields = {
        "title": "Multi-factor authentication",
        "description": "A second factor is required to sign in.",
        "owner": "IT security officer",
        "control_type": Control.ControlType.PREVENTIVE,
        "status": Control.Status.IN_PLACE,
    }
    fields.update(overrides)
    control = Control(**fields)
    control.save()
    return control


class ProcessControlTests(TestCase):
    """Controls chosen as in scope for a process or solution."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.control = make_control()

    def test_linking_shows_on_the_process_and_the_control(self):
        response = self.client.post(
            reverse("processes:process_create"),
            form_data(**{
                "control_links-TOTAL_FORMS": "1",
                "control_links-0-id": "",
                "control_links-0-control": self.control.pk,
            }),
            follow=True,
        )
        process = Process.objects.get()
        self.assertRedirects(response, reverse("processes:process_detail", args=[process.pk]))
        self.assertContains(response, self.control.control_id)
        self.assertContains(response, "Multi-factor authentication")
        control_page = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(control_page, process.process_id)
        self.assertContains(control_page, "Email")

    def test_a_blank_spare_row_adds_nothing(self):
        self.client.post(
            reverse("processes:process_create"),
            form_data(**{
                "control_links-TOTAL_FORMS": "1",
                "control_links-0-id": "",
                "control_links-0-control": "",
            }),
        )
        self.assertFalse(ProcessControl.objects.exists())

    def test_the_same_control_cannot_be_in_scope_twice(self):
        process = make_process(name="Email", kind=Process.Kind.SOLUTION)
        process.save()
        ProcessControl.objects.create(process=process, control=self.control)
        duplicate = ProcessControl(process=process, control=self.control)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save()

    def test_removing_a_control_drops_it_from_scope(self):
        process = make_process(name="Email", kind=Process.Kind.SOLUTION)
        process.save()
        link = ProcessControl.objects.create(process=process, control=self.control)
        self.client.post(
            reverse("processes:process_edit", args=[process.pk]),
            form_data(**{
                "control_links-TOTAL_FORMS": "1",
                "control_links-INITIAL_FORMS": "1",
                "control_links-0-id": link.pk,
                "control_links-0-control": self.control.pk,
                "control_links-0-DELETE": "on",
            }),
        )
        self.assertFalse(process.control_links.exists())

    def test_an_archived_control_cannot_be_newly_added(self):
        self.control.archived_at = timezone.now()
        self.control.save()
        response = self.client.get(reverse("processes:process_create"))
        choices = response.context["link_formset"].forms[0].fields["control"].queryset
        self.assertNotIn(self.control, choices)

    def test_a_linked_process_or_control_cannot_be_deleted(self):
        process = make_process()
        process.save()
        ProcessControl.objects.create(process=process, control=self.control)
        with self.assertRaises(ProtectedError):
            process.delete()
        with self.assertRaises(ProtectedError):
            self.control.delete()
