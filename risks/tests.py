"""
Automated checks for the risk register: scoring, Risk IDs, validation rules
and the admin screen.

Project-wide setup checks live in config/tests.py.
Run with: python manage.py test
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from risks.models import Risk, RiskCategory, calculate_inherent_score, rating_for_score


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
