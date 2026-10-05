"""
Automated checks for the risk register: scoring, Risk IDs, validation rules,
the admin screen, the sample data and backup commands, login, the pages,
change history, archiving and the register's filters.

Project-wide setup checks live in config/tests.py.
Run with: python manage.py test
"""

import datetime
import sqlite3
import stat
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from risks.models import (
    Risk,
    RiskCategory,
    RiskChange,
    calculate_inherent_score,
    rating_for_score,
    score_range_for_rating,
)
from risks.management.commands.backup_db import backup_file_path


def make_risk(category, **overrides):
    """
    Build a valid, unsaved risk for tests.

    Inputs: a category, plus any fields to change from the defaults.
    Output: a Risk object (not yet saved to the database).
    """
    fields = {
        "title": "Ransomware on file server",
        "description": "Made-up test risk.",
        "category": category,
        "owner": "IT manager",
        "risk_source": "File server",
        "inherent_likelihood": 3,
        "inherent_impact": 4,
    }
    fields.update(overrides)
    return Risk(**fields)


def validation_errors(risk):
    """Run all validation on a risk and return the {field: messages} errors."""
    try:
        risk.full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


class ScoringTests(TestCase):
    """Score is likelihood × impact; ratings follow the agreed bands."""

    def test_rating_bands_at_edge_values(self):
        expected = {1: "Low", 4: "Low", 5: "Medium", 9: "Medium",
                    10: "High", 16: "High", 20: "Critical", 25: "Critical"}
        for score, rating in expected.items():
            with self.subTest(score=score):
                self.assertEqual(rating_for_score(score), rating)

    def test_score_is_likelihood_times_impact(self):
        self.assertEqual(calculate_inherent_score(1, 1), 1)
        self.assertEqual(calculate_inherent_score(4, 5), 20)
        self.assertEqual(calculate_inherent_score(5, 5), 25)

    def test_score_is_recalculated_on_every_save(self):
        risk = make_risk(RiskCategory.objects.create(name="Cyber"))
        risk.save()
        self.assertEqual(risk.inherent_score, 12)
        self.assertEqual(risk.inherent_rating, "High")
        risk.inherent_likelihood = 1
        risk.save()
        risk.refresh_from_db()
        self.assertEqual(risk.inherent_score, 4)
        self.assertEqual(risk.inherent_rating, "Low")


class RiskIdTests(TestCase):
    """Risk IDs are generated automatically and do not change."""

    def setUp(self):
        self.category = RiskCategory.objects.create(name="Cyber")

    def test_ids_are_generated_in_sequence(self):
        first = make_risk(self.category)
        first.save()
        second = make_risk(self.category)
        second.save()
        self.assertRegex(first.risk_id, r"^RISK-\d{4}$")
        self.assertEqual(int(second.risk_id[5:]), int(first.risk_id[5:]) + 1)

    def test_id_does_not_change_when_risk_is_edited(self):
        risk = make_risk(self.category)
        risk.save()
        original_id = risk.risk_id
        risk.title = "New title"
        risk.save()
        risk.refresh_from_db()
        self.assertEqual(risk.risk_id, original_id)


class ValidationTests(TestCase):
    """The single-field and response rules from the plan."""

    def setUp(self):
        self.category = RiskCategory.objects.create(name="Cyber")

    def test_valid_risk_passes(self):
        self.assertEqual(validation_errors(make_risk(self.category)), {})

    def test_new_risk_defaults(self):
        risk = make_risk(self.category)
        self.assertEqual(risk.status, Risk.Status.OPEN)
        self.assertEqual(risk.date_identified, timezone.localdate())

    def test_required_fields(self):
        risk = make_risk(self.category, title="", description="", owner="", risk_source="")
        errors = validation_errors(risk)
        for field in ["title", "description", "owner", "risk_source"]:
            self.assertIn(field, errors)

    def test_likelihood_and_impact_outside_1_to_5_are_rejected(self):
        for value in [0, 6]:
            with self.subTest(value=value):
                risk = make_risk(self.category, inherent_likelihood=value, inherent_impact=value)
                errors = validation_errors(risk)
                self.assertIn("inherent_likelihood", errors)
                self.assertIn("inherent_impact", errors)

    def test_database_also_refuses_likelihood_6(self):
        # Bypasses validation on purpose, to test the second line of defence.
        risk = make_risk(self.category, inherent_likelihood=6)
        with self.assertRaises(IntegrityError), transaction.atomic():
            risk.save()

    def test_response_type_needs_description(self):
        risk = make_risk(self.category, response_type=Risk.ResponseType.MITIGATE)
        self.assertIn("response_description", validation_errors(risk))

    def test_in_treatment_and_monitoring_need_response_type(self):
        for status in [Risk.Status.IN_TREATMENT, Risk.Status.MONITORING]:
            with self.subTest(status=status):
                risk = make_risk(self.category, status=status)
                self.assertIn("response_type", validation_errors(risk))

    def test_open_and_closed_do_not_need_response_type(self):
        for status in [Risk.Status.OPEN, Risk.Status.CLOSED]:
            with self.subTest(status=status):
                self.assertEqual(validation_errors(make_risk(self.category, status=status)), {})


class AcceptanceTests(TestCase):
    """The risk-acceptance fields are required for Accept and empty otherwise."""

    def setUp(self):
        self.category = RiskCategory.objects.create(name="Cyber")

    def make_accepted_risk(self, **overrides):
        """Build a valid accepted risk, with any fields changed by `overrides`."""
        fields = {
            "response_type": Risk.ResponseType.ACCEPT,
            "response_description": "Within appetite.",
            "accepted_by": "CISO",
            "acceptance_date": datetime.date(2026, 1, 1),
            "acceptance_expiry_date": datetime.date(2027, 1, 1),
        }
        fields.update(overrides)
        return make_risk(self.category, **fields)

    def test_complete_acceptance_passes(self):
        self.assertEqual(validation_errors(self.make_accepted_risk()), {})

    def test_accept_requires_approver_and_dates(self):
        risk = self.make_accepted_risk(
            accepted_by="", acceptance_date=None, acceptance_expiry_date=None
        )
        errors = validation_errors(risk)
        for field in ["accepted_by", "acceptance_date", "acceptance_expiry_date"]:
            self.assertIn(field, errors)

    def test_expiry_must_be_after_acceptance_date(self):
        for expiry in [datetime.date(2026, 1, 1), datetime.date(2025, 12, 31)]:
            with self.subTest(expiry=expiry):
                risk = self.make_accepted_risk(acceptance_expiry_date=expiry)
                self.assertIn("acceptance_expiry_date", validation_errors(risk))

    def test_acceptance_fields_must_be_empty_for_other_responses(self):
        risk = self.make_accepted_risk(response_type=Risk.ResponseType.MITIGATE)
        errors = validation_errors(risk)
        for field in ["accepted_by", "acceptance_date", "acceptance_expiry_date"]:
            self.assertIn(field, errors)


class CategoryTests(TestCase):
    """Category names are unique and used categories cannot be deleted."""

    def test_category_in_use_cannot_be_deleted(self):
        category = RiskCategory.objects.create(name="Cyber")
        make_risk(category).save()
        with self.assertRaises(ProtectedError):
            category.delete()

    def test_category_names_are_unique(self):
        RiskCategory.objects.create(name="Cyber")
        with self.assertRaises(ValidationError):
            RiskCategory(name="Cyber").full_clean()


class AdminTests(TestCase):
    """The admin screen applies the model rules and protects archived risks."""

    def setUp(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(admin_user)
        self.category = RiskCategory.objects.create(name="Cyber")

    def admin_form_data(self, **overrides):
        """Return valid form data for the admin's add/change risk page."""
        data = {
            "title": "Phishing",
            "description": "Made-up test risk.",
            "category": self.category.pk,
            "owner": "IT manager",
            "risk_source": "Email",
            "date_identified": "05/10/2026",
            "inherent_likelihood": 4,
            "inherent_impact": 5,
            "status": Risk.Status.OPEN,
        }
        data.update(overrides)
        return data

    def test_add_risk_generates_id_score_and_rating(self):
        response = self.client.post(reverse("admin:risks_risk_add"), self.admin_form_data())
        self.assertEqual(response.status_code, 302)  # redirect = saved
        risk = Risk.objects.get()
        self.assertTrue(risk.risk_id.startswith("RISK-"))
        self.assertEqual(risk.inherent_score, 20)
        self.assertEqual(risk.inherent_rating, "Critical")

    def test_admin_rejects_invalid_risks(self):
        invalid_inputs = {
            "likelihood 6": {"inherent_likelihood": 6},
            "response type without description": {"response_type": Risk.ResponseType.MITIGATE},
            "accept without approver": {
                "response_type": Risk.ResponseType.ACCEPT,
                "response_description": "Within appetite.",
                "acceptance_date": "01/01/2026",
                "acceptance_expiry_date": "01/01/2027",
            },
        }
        for name, overrides in invalid_inputs.items():
            with self.subTest(name):
                response = self.client.post(
                    reverse("admin:risks_risk_add"), self.admin_form_data(**overrides)
                )
                self.assertEqual(response.status_code, 200)  # form shown again
                self.assertTrue(response.context["adminform"].form.errors)
        self.assertFalse(Risk.objects.exists())

    def test_archived_risk_cannot_be_edited_in_admin(self):
        risk = make_risk(self.category, archived_at=timezone.now())
        risk.save()
        change_url = reverse("admin:risks_risk_change", args=[risk.pk])

        page = self.client.get(change_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="_save"')  # no Save button

        response = self.client.post(change_url, self.admin_form_data(title="Changed"))
        self.assertEqual(response.status_code, 403)
        risk.refresh_from_db()
        self.assertEqual(risk.title, "Ransomware on file server")

    def test_risks_cannot_be_deleted_in_admin(self):
        risk = make_risk(self.category)
        risk.save()
        response = self.client.post(reverse("admin:risks_risk_delete", args=[risk.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Risk.objects.filter(pk=risk.pk).exists())


class SampleDataTests(TestCase):
    """The load_sample_risks command loads valid, varied data exactly once."""

    def load_sample_risks(self):
        """Run the command, hiding its output. Output: the printed message."""
        output = StringIO()
        call_command("load_sample_risks", stdout=output)
        return output.getvalue()

    def test_loads_starting_categories(self):
        self.load_sample_risks()
        self.assertEqual(
            set(RiskCategory.objects.values_list("name", flat=True)),
            {"Cyber", "Operational", "Compliance", "Third party", "Strategic", "Financial"},
        )

    def test_running_twice_does_not_create_duplicates(self):
        self.load_sample_risks()
        risk_count = Risk.objects.count()
        category_count = RiskCategory.objects.count()
        self.assertGreaterEqual(risk_count, 10)

        message = self.load_sample_risks()
        self.assertEqual(Risk.objects.count(), risk_count)
        self.assertEqual(RiskCategory.objects.count(), category_count)
        self.assertIn("Risks created: 0", message)

    def test_existing_edits_are_kept(self):
        self.load_sample_risks()
        risk = Risk.objects.first()
        risk.owner = "Changed owner"
        risk.save()
        self.load_sample_risks()
        risk.refresh_from_db()
        self.assertEqual(risk.owner, "Changed owner")

    def test_covers_every_rating_and_status(self):
        self.load_sample_risks()
        risks = Risk.objects.all()
        self.assertEqual(
            {risk.inherent_rating for risk in risks}, {"Low", "Medium", "High", "Critical"}
        )
        self.assertEqual({risk.status for risk in risks}, set(Risk.Status.values))

    def test_includes_an_expired_acceptance(self):
        self.load_sample_risks()
        expired = Risk.objects.filter(
            response_type=Risk.ResponseType.ACCEPT,
            acceptance_expiry_date__lt=timezone.localdate(),
        )
        self.assertTrue(expired.exists())

    def test_all_sample_risks_pass_validation(self):
        self.load_sample_risks()
        for risk in Risk.objects.all():
            with self.subTest(risk.title):
                self.assertEqual(validation_errors(risk), {})


class AcceptanceExpiryTests(TestCase):
    """An acceptance counts as expired from the day after its expiry date."""

    def make_accepted_risk(self, expiry_date):
        """Build an accepted risk (unsaved) with the given expiry date."""
        return make_risk(
            RiskCategory(name="Cyber"),
            response_type=Risk.ResponseType.ACCEPT,
            acceptance_expiry_date=expiry_date,
        )

    def test_expiry_flag(self):
        today = timezone.localdate()
        one_day = datetime.timedelta(days=1)
        self.assertTrue(self.make_accepted_risk(today - one_day).is_acceptance_expired)
        self.assertFalse(self.make_accepted_risk(today).is_acceptance_expired)
        self.assertFalse(self.make_accepted_risk(today + one_day).is_acceptance_expired)

    def test_non_accepted_risk_is_never_expired(self):
        risk = make_risk(RiskCategory(name="Cyber"), response_type=Risk.ResponseType.MITIGATE)
        self.assertFalse(risk.is_acceptance_expired)


class LoginRequiredTests(TestCase):
    """Logged-out visitors are sent to the login page."""

    def test_pages_redirect_to_login_when_logged_out(self):
        risk = make_risk(RiskCategory.objects.create(name="Cyber"))
        risk.save()
        for url in [reverse("risks:risk_list"), reverse("risks:risk_detail", args=[risk.pk])]:
            with self.subTest(url):
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_login_page_is_open_and_login_works(self):
        get_user_model().objects.create_user(username="w", password="test-password-123")
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        response = self.client.post(
            reverse("login"), {"username": "w", "password": "test-password-123"}
        )
        self.assertRedirects(response, reverse("risks:risk_list"))

    def test_wrong_password_is_refused(self):
        get_user_model().objects.create_user(username="w", password="test-password-123")
        response = self.client.post(reverse("login"), {"username": "w", "password": "wrong"})
        self.assertContains(response, "didn't match")

    def test_admin_login_page_still_works(self):
        self.assertEqual(self.client.get(reverse("admin:login")).status_code, 200)

    def test_logout_logs_the_user_out(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertEqual(self.client.get(reverse("risks:risk_list")).status_code, 302)


class RiskPagesTests(TestCase):
    """The list and detail pages show the right risks and flags."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        self.category = RiskCategory.objects.create(name="Cyber")

    def save_risk(self, **overrides):
        """Create and save a risk with the given field changes. Output: the risk."""
        risk = make_risk(self.category, **overrides)
        risk.save()
        return risk

    def test_list_shows_active_risks_only(self):
        self.save_risk(title="Open risk")
        self.save_risk(title="Monitored risk", status=Risk.Status.MONITORING,
                       response_type=Risk.ResponseType.MITIGATE, response_description="MFA")
        self.save_risk(title="Closed risk", status=Risk.Status.CLOSED)
        self.save_risk(title="Archived risk", archived_at=timezone.now())

        response = self.client.get(reverse("risks:risk_list"))
        self.assertEqual(response.status_code, 200)
        titles = {risk.title for risk in response.context["risks"]}
        self.assertEqual(titles, {"Open risk", "Monitored risk"})

    def test_list_shows_columns_and_rating(self):
        risk = self.save_risk(inherent_likelihood=5, inherent_impact=5)
        response = self.client.get(reverse("risks:risk_list"))
        for text in [risk.risk_id, risk.title, risk.owner, "Cyber", "25", "Critical", "Open"]:
            self.assertContains(response, text)
        self.assertContains(response, 'class="rating rating-critical"')

    def test_expired_acceptance_is_flagged_on_both_pages(self):
        today = timezone.localdate()
        expired = self.save_risk(
            response_type=Risk.ResponseType.ACCEPT,
            response_description="Within appetite.",
            accepted_by="CISO",
            acceptance_date=today - datetime.timedelta(days=400),
            acceptance_expiry_date=today - datetime.timedelta(days=1),
        )
        self.assertContains(self.client.get(reverse("risks:risk_list")), "Acceptance expired")
        detail = self.client.get(reverse("risks:risk_detail", args=[expired.pk]))
        self.assertContains(detail, "Acceptance expired")

    def test_valid_risk_is_not_flagged(self):
        risk = self.save_risk()
        self.assertNotContains(self.client.get(reverse("risks:risk_list")), "Acceptance expired")
        detail = self.client.get(reverse("risks:risk_detail", args=[risk.pk]))
        self.assertNotContains(detail, "Acceptance expired")

    def test_detail_page_shows_fields_with_labels(self):
        risk = self.save_risk(notes="Some notes")
        response = self.client.get(reverse("risks:risk_detail", args=[risk.pk]))
        for text in [risk.risk_id, risk.title, risk.description, risk.risk_source,
                     "3 – Possible", "4 – Major", "12", "High", "Some notes"]:
            self.assertContains(response, text)

    def test_detail_page_of_unknown_risk_is_not_found(self):
        response = self.client.get(reverse("risks:risk_detail", args=[9999]))
        self.assertEqual(response.status_code, 404)


def risk_form_data(category, **overrides):
    """Return valid data for the New/Edit risk form, with any fields changed."""
    data = {
        "title": "Ransomware on file server",
        "description": "Made-up test risk.",
        "category": category.pk,
        "owner": "IT manager",
        "risk_source": "File server",
        "date_identified": "2026-10-05",
        "inherent_likelihood": 3,
        "inherent_impact": 4,
        "status": Risk.Status.OPEN,
    }
    data.update(overrides)
    return data


class RiskFormPagesTests(TestCase):
    """The New and Edit pages validate input and record history."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.category = RiskCategory.objects.create(name="Cyber")

    def test_empty_form_is_rejected_with_messages(self):
        response = self.client.post(reverse("risks:risk_create"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(response, "This field is required.")
        self.assertFalse(Risk.objects.exists())

    def test_model_rules_apply_to_the_form(self):
        data = risk_form_data(self.category, response_type=Risk.ResponseType.ACCEPT,
                              response_description="Within appetite.")
        response = self.client.post(reverse("risks:risk_create"), data)
        self.assertContains(response, "Record who accepted the risk.")
        self.assertFalse(Risk.objects.exists())

    def test_form_shows_scale_labels(self):
        response = self.client.get(reverse("risks:risk_create"))
        self.assertContains(response, "3 – Possible")
        self.assertContains(response, "5 – Severe")

    def test_create_saves_risk_and_records_created(self):
        response = self.client.post(reverse("risks:risk_create"), risk_form_data(self.category))
        risk = Risk.objects.get()
        self.assertRedirects(response, reverse("risks:risk_detail", args=[risk.pk]))
        self.assertEqual(risk.inherent_score, 12)
        change = risk.changes.get()
        self.assertEqual(change.field_name, "Created")
        self.assertEqual(change.changed_by, self.user)

    def test_edit_records_one_row_per_changed_field(self):
        self.client.post(reverse("risks:risk_create"), risk_form_data(self.category))
        risk = Risk.objects.get()

        self.client.post(
            reverse("risks:risk_edit", args=[risk.pk]),
            risk_form_data(self.category, inherent_likelihood=4),
        )
        changes = {c.field_name: (c.old_value, c.new_value)
                   for c in risk.changes.exclude(field_name="Created")}
        self.assertEqual(changes, {
            "Inherent likelihood": ("3 – Possible", "4 – Likely"),
            "Inherent score": ("12", "16"),
        })

    def test_saving_without_changes_records_nothing(self):
        self.client.post(reverse("risks:risk_create"), risk_form_data(self.category))
        risk = Risk.objects.get()
        self.client.post(reverse("risks:risk_edit", args=[risk.pk]), risk_form_data(self.category))
        self.assertEqual(risk.changes.count(), 1)  # only "Created"

    def test_history_is_shown_newest_first(self):
        self.client.post(reverse("risks:risk_create"), risk_form_data(self.category))
        risk = Risk.objects.get()
        self.client.post(reverse("risks:risk_edit", args=[risk.pk]),
                         risk_form_data(self.category, owner="CISO"))
        page = self.client.get(reverse("risks:risk_detail", args=[risk.pk])).content.decode()
        self.assertLess(page.index("CISO"), page.index("Created"))

    def test_archived_risk_cannot_be_edited(self):
        risk = make_risk(self.category, archived_at=timezone.now())
        risk.save()
        edit_url = reverse("risks:risk_edit", args=[risk.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        response = self.client.post(edit_url, risk_form_data(self.category, title="Changed"))
        self.assertEqual(response.status_code, 403)
        risk.refresh_from_db()
        self.assertEqual(risk.title, "Ransomware on file server")

    def test_users_without_permission_cannot_create_or_edit(self):
        risk = make_risk(self.category)
        risk.save()
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("risks:risk_create")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("risks:risk_edit", args=[risk.pk])).status_code, 403
        )
        detail = self.client.get(reverse("risks:risk_detail", args=[risk.pk]))
        self.assertNotContains(detail, ">Edit</a>")


class AdminHistoryTests(TestCase):
    """Saves made in the admin screen are also recorded in the history."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.category = RiskCategory.objects.create(name="Cyber")

    def test_admin_add_and_edit_are_recorded(self):
        data = risk_form_data(self.category, date_identified="05/10/2026")
        self.client.post(reverse("admin:risks_risk_add"), data)
        risk = Risk.objects.get()

        data["status"] = Risk.Status.CLOSED
        self.client.post(reverse("admin:risks_risk_change", args=[risk.pk]), data)

        rows = [(c.field_name, c.old_value, c.new_value, c.changed_by)
                for c in risk.changes.all()]
        self.assertEqual(rows, [
            ("Status", "Open", "Closed", self.user),
            ("Created", "", risk.risk_id, self.user),
        ])


class HistoryRowProtectionTests(TestCase):
    """History rows cannot be edited or deleted."""

    def test_history_rows_are_write_once(self):
        user = get_user_model().objects.create_user(username="w", password="x-Long-pw-123")
        risk = make_risk(RiskCategory.objects.create(name="Cyber"))
        risk.save()
        change = RiskChange.objects.create(risk=risk, field_name="Created", changed_by=user)
        change.new_value = "tampered"
        with self.assertRaises(ValueError):
            change.save()
        with self.assertRaises(ValueError):
            change.delete()
        with self.assertRaises(ProtectedError):
            risk.delete()


class ArchiveTests(TestCase):
    """Archiving hides a risk from the register; restoring brings it back."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.risk = make_risk(RiskCategory.objects.create(name="Cyber"),
                              title="Risk to archive", status=Risk.Status.CLOSED)
        self.risk.save()
        self.archive_url = reverse("risks:risk_archive", args=[self.risk.pk])
        self.restore_url = reverse("risks:risk_restore", args=[self.risk.pk])

    def test_confirmation_page_does_not_archive_yet(self):
        response = self.client.get(self.archive_url)
        self.assertContains(response, "Archive risk")
        self.risk.refresh_from_db()
        self.assertIsNone(self.risk.archived_at)

    def test_archive_hides_from_register_and_shows_in_archive(self):
        self.risk.status = Risk.Status.OPEN
        self.risk.save()
        self.assertContains(self.client.get(reverse("risks:risk_list")), "Risk to archive")

        response = self.client.post(self.archive_url)
        self.assertRedirects(response, reverse("risks:risk_list"))
        self.risk.refresh_from_db()
        self.assertIsNotNone(self.risk.archived_at)
        self.assertEqual(self.risk.status, Risk.Status.OPEN)  # status is kept
        self.assertNotContains(self.client.get(reverse("risks:risk_list")), "Risk to archive")
        self.assertContains(self.client.get(reverse("risks:archived_risk_list")), "Risk to archive")

    def test_restore_brings_risk_back(self):
        self.client.post(self.archive_url)
        response = self.client.post(self.restore_url)
        self.assertRedirects(response, reverse("risks:risk_detail", args=[self.risk.pk]))
        self.risk.refresh_from_db()
        self.assertIsNone(self.risk.archived_at)
        self.assertNotContains(
            self.client.get(reverse("risks:archived_risk_list")), "Risk to archive"
        )

    def test_archive_and_restore_are_recorded_in_history(self):
        self.client.post(self.archive_url)
        self.client.post(self.restore_url)
        events = [(c.field_name, c.changed_by) for c in self.risk.changes.all()]
        self.assertEqual(events, [("Restored", self.user), ("Archived", self.user)])

    def test_archiving_twice_records_one_event(self):
        self.client.post(self.archive_url)
        self.client.post(self.archive_url)
        self.assertEqual(self.risk.changes.filter(field_name="Archived").count(), 1)

    def test_archived_risk_detail_shows_restore_not_edit(self):
        self.client.post(self.archive_url)
        response = self.client.get(reverse("risks:risk_detail", args=[self.risk.pk]))
        self.assertContains(response, "read-only until it is restored")
        self.assertContains(response, ">Restore</button>")
        self.assertNotContains(response, ">Edit</a>")

    def test_edit_page_refused_while_archived(self):
        self.client.post(self.archive_url)
        response = self.client.get(reverse("risks:risk_edit", args=[self.risk.pk]))
        self.assertEqual(response.status_code, 403)

    def test_restore_only_accepts_form_submissions(self):
        self.client.post(self.archive_url)
        self.assertEqual(self.client.get(self.restore_url).status_code, 405)
        self.risk.refresh_from_db()
        self.assertIsNotNone(self.risk.archived_at)

    def test_users_without_permission_cannot_archive_or_restore(self):
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.archive_url).status_code, 403)
        self.risk.refresh_from_db()
        self.assertIsNone(self.risk.archived_at)

        self.client.force_login(self.user)
        self.client.post(self.archive_url)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.restore_url).status_code, 403)
        archive_page = self.client.get(reverse("risks:archived_risk_list"))
        self.assertNotContains(archive_page, ">Restore</button>")


class RatingRangeTests(TestCase):
    """Each rating maps to the score range of its band."""

    def test_score_ranges(self):
        self.assertEqual(score_range_for_rating("Low"), (1, 4))
        self.assertEqual(score_range_for_rating("Medium"), (5, 9))
        self.assertEqual(score_range_for_rating("High"), (10, 16))
        self.assertEqual(score_range_for_rating("Critical"), (17, 25))


class RegisterFilterTests(TestCase):
    """Filters, search and sorting on the register page."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        cyber = RiskCategory.objects.create(name="Cyber")
        finance = RiskCategory.objects.create(name="Financial")
        mitigate = {"response_type": Risk.ResponseType.MITIGATE, "response_description": "MFA"}
        # (title, category, likelihood, impact, status) -> scores 16, 20, 4, 12, 6
        for title, category, likelihood, impact, status in [
            ("Phishing attack", cyber, 4, 4, Risk.Status.OPEN),
            ("Currency swings", finance, 4, 5, Risk.Status.IN_TREATMENT),
            ("Old printer", cyber, 1, 4, Risk.Status.CLOSED),
            ("Supplier outage", finance, 3, 4, Risk.Status.MONITORING),
            ("Archived thing", cyber, 2, 3, Risk.Status.OPEN),
        ]:
            extra = mitigate if status in (Risk.Status.IN_TREATMENT, Risk.Status.MONITORING) else {}
            make_risk(category, title=title, inherent_likelihood=likelihood,
                      inherent_impact=impact, status=status, **extra).save()
        Risk.objects.filter(title="Archived thing").update(archived_at=timezone.now())
        self.cyber = cyber

    def titles_shown(self, **params):
        """Open the register with the given filters. Output: titles in display order."""
        response = self.client.get(reverse("risks:risk_list"), params)
        self.assertEqual(response.status_code, 200)
        return [risk.title for risk in response.context["risks"]]

    def test_default_shows_active_non_archived_risks(self):
        self.assertEqual(self.titles_shown(),
                         ["Phishing attack", "Currency swings", "Supplier outage"])

    def test_status_filter(self):
        self.assertEqual(self.titles_shown(status="closed"), ["Old printer"])
        self.assertEqual(self.titles_shown(status="open"), ["Phishing attack"])
        self.assertEqual(len(self.titles_shown(status="all")), 4)  # archived still excluded

    def test_category_filter(self):
        self.assertEqual(self.titles_shown(category=self.cyber.pk), ["Phishing attack"])

    def test_rating_filter(self):
        self.assertEqual(self.titles_shown(rating="High"), ["Phishing attack", "Supplier outage"])
        self.assertEqual(self.titles_shown(rating="Critical"), ["Currency swings"])
        self.assertEqual(self.titles_shown(rating="Low", status="all"), ["Old printer"])

    def test_filters_combine(self):
        self.assertEqual(self.titles_shown(rating="High", status="open"), ["Phishing attack"])

    def test_search_title_and_description_ignoring_case(self):
        self.assertEqual(self.titles_shown(q="PHISH"), ["Phishing attack"])
        # make_risk gives every risk the description "Made-up test risk."
        self.assertEqual(len(self.titles_shown(q="made-up")), 3)
        self.assertEqual(self.titles_shown(q="nothing like this"), [])

    def test_sort_by_score_both_directions(self):
        self.assertEqual(self.titles_shown(sort="score"),
                         ["Supplier outage", "Phishing attack", "Currency swings"])
        self.assertEqual(self.titles_shown(sort="-score"),
                         ["Currency swings", "Phishing attack", "Supplier outage"])

    def test_sort_by_status_follows_lifecycle(self):
        self.assertEqual(self.titles_shown(sort="status", status="all"),
                         ["Phishing attack", "Currency swings", "Supplier outage", "Old printer"])

    def test_invalid_values_are_ignored(self):
        default = self.titles_shown()
        self.assertEqual(self.titles_shown(status="nonsense", sort="password", rating="Huge",
                                           category="abc"), default)

    def test_sort_links_keep_filters_and_reverse_direction(self):
        response = self.client.get(reverse("risks:risk_list"), {"status": "all", "sort": "score"})
        score_column = next(c for c in response.context["columns"] if c["label"] == "Inherent score")
        self.assertIn("status=all", score_column["query"])
        self.assertIn("sort=-score", score_column["query"])
        self.assertEqual(score_column["arrow"], "▲")

    def test_closed_option_reaches_closed_sample_risk(self):
        response = self.client.get(reverse("risks:risk_list"), {"status": "closed"})
        self.assertContains(response, "Old printer")
        self.assertContains(response, "Clear filters")


class BackupTests(TransactionTestCase):
    """
    The backup_db command writes a sound, dated, private copy of the database.

    TransactionTestCase saves test data for real (instead of inside an
    unfinished transaction), so the backup can read it, as it would in use.
    """

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / "backups"
        make_risk(RiskCategory.objects.create(name="Cyber"), title="Backed-up risk").save()

    def run_backup(self):
        """Run the command into the temporary folder. Output: the printed message."""
        output = StringIO()
        call_command("backup_db", folder=self.folder, stdout=output)
        return output.getvalue()

    def test_backup_file_is_dated_and_contains_the_data(self):
        message = self.run_backup()
        backups = list(self.folder.glob("*.db"))
        self.assertEqual(len(backups), 1)
        self.assertRegex(backups[0].name, r"^grc-\d{4}-\d{2}-\d{2}-\d{4}\.db$")
        self.assertIn("Backup written", message)

        copy = sqlite3.connect(backups[0])
        titles = [row[0] for row in copy.execute("SELECT title FROM risks_risk")]
        copy.close()
        self.assertEqual(titles, ["Backed-up risk"])

    def test_backup_never_overwrites_an_earlier_one(self):
        self.run_backup()
        self.run_backup()
        self.assertEqual(len(list(self.folder.glob("*.db"))), 2)

    def test_backup_file_name_counter(self):
        now = timezone.localtime()
        self.folder.mkdir(parents=True)
        first = backup_file_path(self.folder, now)
        first.touch()
        self.assertEqual(backup_file_path(self.folder, now).name, first.stem + "-2.db")

    def test_backup_is_readable_by_owner_only(self):
        self.run_backup()
        backup = next(self.folder.glob("*.db"))
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o700)

    def test_backups_folder_is_excluded_from_git(self):
        gitignore = (settings.BASE_DIR / ".gitignore").read_text().splitlines()
        self.assertIn("backups/", gitignore)
