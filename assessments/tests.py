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


class AssessmentPageTests(TestCase):
    """The assessment list and detail pages, and the rows on a risk or control."""

    def setUp(self):
        user = get_user_model().objects.create_user(username="w", password="test-password-123")
        self.client.force_login(user)
        self.risk = make_risk_for_links()
        self.control = make_control()
        self.control.save()
        self.test = make_assessment(
            control=self.control,
            status=Assessment.Status.COMPLETE,
            outcome=Assessment.Outcome.SATISFACTORY,
            findings="The second factor is required for email.",
            evidence="Walkthrough of the email sign-in screen.",
        )
        self.test.save()
        self.review = make_assessment(
            title="Phishing review",
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=self.risk,
            control=None,
        )
        self.review.save()

    def test_logged_out_visitors_are_sent_to_login(self):
        self.client.logout()
        url = reverse("assessments:assessment_list")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_list_shows_active_assessments_and_hides_archived_ones(self):
        archived = make_assessment(title="Old review", control=self.control, archived_at=timezone.now())
        archived.save()
        response = self.client.get(reverse("assessments:assessment_list"))
        self.assertContains(response, "ASMT-0001")
        self.assertContains(response, "MFA operating check")
        self.assertContains(response, "Satisfactory")
        self.assertContains(response, self.control.control_id)
        self.assertContains(response, "Phishing review")
        self.assertContains(response, self.risk.risk_id)
        self.assertNotContains(response, "Old review")

    def test_detail_shows_the_finding_and_links_to_the_control(self):
        response = self.client.get(reverse("assessments:assessment_detail", args=[self.test.pk]))
        self.assertContains(response, "The second factor is required for email.")
        self.assertContains(response, "Walkthrough of the email sign-in screen.")
        self.assertContains(response, "Internal audit")
        control_url = reverse("controls:control_detail", args=[self.control.pk])
        self.assertContains(response, f'href="{control_url}"')

    def test_control_page_lists_its_tests_and_risk_page_lists_its_reviews(self):
        control_page = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(control_page, "MFA operating check")
        self.assertNotContains(control_page, "Phishing review")

        risk_page = self.client.get(reverse("risks:risk_detail", args=[self.risk.pk]))
        self.assertContains(risk_page, "Phishing review")
        self.assertNotContains(risk_page, "MFA operating check")

    def test_unknown_assessment_is_not_found(self):
        response = self.client.get(reverse("assessments:assessment_detail", args=[9999]))
        self.assertEqual(response.status_code, 404)
