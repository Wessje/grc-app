"""
Automated checks for assessments: the subject rules, the result rules,
Assessment IDs and the admin screen.

Run with: python manage.py test
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assessments.models import Assessment
from controls.tests import make_control, make_risk_for_links


def make_assessment(**overrides):
    """
    Build a valid, unsaved control test for tests.

    Input: any fields to change from the defaults. A control is created and
    saved when one is not supplied, because a control test must name one.
    Output: an Assessment object (not yet saved to the database).
    """
    if "control" not in overrides and "risk" not in overrides:
        control = make_control()
        control.save()
        overrides["control"] = control
    fields = {
        "title": "MFA operating check",
        "assessment_type": Assessment.AssessmentType.CONTROL_TEST,
        "review_date": datetime.date(2026, 10, 7),
        "reviewer": "Internal audit",
        "findings": "",
        "evidence": "",
    }
    fields.update(overrides)
    return Assessment(**fields)


def validation_errors(assessment):
    """Run all validation on an assessment and return the {field: messages} errors."""
    try:
        assessment.full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


class AssessmentTests(TestCase):
    """Subject rules, result rules and Assessment IDs."""

    def test_valid_planned_control_test_passes(self):
        self.assertEqual(validation_errors(make_assessment()), {})

    def test_new_assessment_defaults_to_planned(self):
        self.assertEqual(make_assessment().status, Assessment.Status.PLANNED)

    def test_control_test_needs_a_control_and_no_risk(self):
        risk = make_risk_for_links()
        missing = make_assessment(control=None)
        self.assertIn("control", validation_errors(missing))

        both = make_assessment(risk=risk)
        self.assertIn("risk", validation_errors(both))

    def test_risk_review_needs_a_risk_and_no_control(self):
        risk = make_risk_for_links()
        control = make_control(title="Backups")
        control.save()
        missing = make_assessment(
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            control=None,
        )
        self.assertIn("risk", validation_errors(missing))

        both = make_assessment(
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=risk,
            control=control,
        )
        self.assertIn("control", validation_errors(both))

        review = make_assessment(
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=risk,
            control=None,
        )
        self.assertEqual(validation_errors(review), {})

    def test_complete_assessment_needs_outcome_finding_and_evidence(self):
        assessment = make_assessment(status=Assessment.Status.COMPLETE)
        errors = validation_errors(assessment)
        self.assertIn("outcome", errors)
        self.assertIn("findings", errors)
        self.assertIn("evidence", errors)

        assessment.outcome = Assessment.Outcome.SATISFACTORY
        assessment.findings = "The second factor is required for email."
        assessment.evidence = "Walkthrough of the email sign-in screen."
        self.assertEqual(validation_errors(assessment), {})

    def test_planned_assessment_cannot_have_an_outcome(self):
        assessment = make_assessment(outcome=Assessment.Outcome.SATISFACTORY)
        self.assertIn("outcome", validation_errors(assessment))

    def test_next_review_must_be_after_the_review_date(self):
        assessment = make_assessment(next_review_date=datetime.date(2026, 10, 7))
        self.assertIn("next_review_date", validation_errors(assessment))
        assessment.next_review_date = datetime.date(2027, 10, 7)
        self.assertEqual(validation_errors(assessment), {})

    def test_assessment_id_is_assigned_once_and_never_reused(self):
        first = make_assessment()
        first.save()
        second = make_assessment(title="Backup restore test")
        second.save()
        self.assertEqual(first.assessment_id, "ASMT-0001")
        self.assertEqual(second.assessment_id, "ASMT-0002")

        original_id = first.assessment_id
        first.title = "New title"
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.assessment_id, original_id)

    def test_saving_an_assessment_does_not_change_the_risk_score(self):
        risk = make_risk_for_links()
        risk.residual_likelihood = 2
        risk.residual_impact = 2
        risk.save()
        score_before = risk.residual_score

        review = make_assessment(
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=risk,
            control=None,
            status=Assessment.Status.COMPLETE,
            outcome=Assessment.Outcome.UNSATISFACTORY,
            findings="The phishing exposure is still open.",
            evidence="Sample of reported phishing emails.",
        )
        review.save()
        risk.refresh_from_db()
        self.assertEqual(risk.residual_score, score_before)
        self.assertEqual(risk.residual_likelihood, 2)

    def test_a_reviewed_risk_or_tested_control_cannot_be_deleted(self):
        risk = make_risk_for_links()
        review = make_assessment(
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=risk,
            control=None,
        )
        review.save()
        with self.assertRaises(ProtectedError):
            risk.delete()

        test = make_assessment()
        test.save()
        with self.assertRaises(ProtectedError):
            test.control.delete()


class AssessmentAdminTests(TestCase):
    """The admin screen applies the rules and protects archived assessments."""

    def setUp(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin", password="test-password-123"
        )
        self.client.force_login(admin_user)
        self.control = make_control()
        self.control.save()

    def admin_form_data(self, **overrides):
        """Return valid form data for the admin's add/change assessment page."""
        data = {
            "title": "MFA operating check",
            "assessment_type": Assessment.AssessmentType.CONTROL_TEST,
            "risk": "",
            "control": self.control.pk,
            "review_date": "07/10/2026",
            "reviewer": "Internal audit",
            "status": Assessment.Status.PLANNED,
            "outcome": "",
            "findings": "",
            "evidence": "",
            "next_review_date": "",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_add_assessment_generates_id(self):
        response = self.client.post(
            reverse("admin:assessments_assessment_add"), self.admin_form_data()
        )
        self.assertEqual(response.status_code, 302)
        assessment = Assessment.objects.get()
        self.assertEqual(assessment.assessment_id, "ASMT-0001")
        self.assertEqual(assessment.control, self.control)

    def test_admin_rejects_a_risk_review_without_a_risk(self):
        response = self.client.post(
            reverse("admin:assessments_assessment_add"),
            self.admin_form_data(
                assessment_type=Assessment.AssessmentType.RISK_REVIEW,
                control="",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("risk", response.context["adminform"].form.errors)
        self.assertFalse(Assessment.objects.exists())

    def test_admin_rejects_a_complete_test_without_an_outcome(self):
        response = self.client.post(
            reverse("admin:assessments_assessment_add"),
            self.admin_form_data(status=Assessment.Status.COMPLETE),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("outcome", response.context["adminform"].form.errors)
        self.assertFalse(Assessment.objects.exists())

    def test_archived_assessment_cannot_be_edited_in_admin(self):
        assessment = make_assessment(control=self.control, archived_at=timezone.now())
        assessment.save()
        change_url = reverse("admin:assessments_assessment_change", args=[assessment.pk])

        page = self.client.get(change_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="_save"')

        response = self.client.post(change_url, self.admin_form_data(title="Changed"))
        self.assertEqual(response.status_code, 403)
        assessment.refresh_from_db()
        self.assertEqual(assessment.title, "MFA operating check")

    def test_assessments_cannot_be_deleted_in_admin(self):
        assessment = make_assessment(control=self.control)
        assessment.save()
        response = self.client.post(
            reverse("admin:assessments_assessment_delete", args=[assessment.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Assessment.objects.filter(pk=assessment.pk).exists())
