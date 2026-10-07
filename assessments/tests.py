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

from assessments.models import AssessedControl, Assessment
from controls.models import RiskControl
from controls.tests import make_control, make_risk_for_links
from processes.models import Process, ProcessControl
from risks.models import Risk, RiskCategory
from risks.tests import make_risk


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

    def test_filters_search_and_an_unknown_value_is_ignored(self):
        process = Process.objects.create(
            kind=Process.Kind.SOLUTION, name="Email", description="Staff email.", owner="IT manager",
        )
        review = make_assessment(
            title="Email backup check",
            assessment_type=Assessment.AssessmentType.PROCESS_REVIEW,
            process=process,
            control=None,
            status=Assessment.Status.PLANNED,
        )
        review.save()
        by_type = self.client.get(
            reverse("assessments:assessment_list"), {"assessment_type": "process_review"}
        )
        self.assertContains(by_type, "Email backup check")
        self.assertNotContains(by_type, "MFA operating check")

        by_subject = self.client.get(reverse("assessments:assessment_list"), {"q": "Email"})
        self.assertContains(by_subject, "Email backup check")
        self.assertNotContains(by_subject, "Phishing review")

        planned = self.client.get(reverse("assessments:assessment_list"), {"status": "planned"})
        self.assertContains(planned, "Phishing review")
        self.assertNotContains(planned, "MFA operating check")

        unknown = self.client.get(reverse("assessments:assessment_list"), {"status": "nope"})
        self.assertContains(unknown, "MFA operating check")
        self.assertContains(unknown, "Email backup check")

    def test_readers_do_not_see_new_or_edit(self):
        listing = self.client.get(reverse("assessments:assessment_list"))
        self.assertNotContains(listing, ">New assessment</a>")
        detail = self.client.get(reverse("assessments:assessment_detail", args=[self.test.pk]))
        self.assertNotContains(detail, ">Edit</a>")


def assessment_form_data(control, **overrides):
    """
    Build a valid submission for the New assessment and Edit pages.

    Input: the control the test covers, and any fields to change.
    Output: a dictionary the test client can post.
    """
    data = {
        "title": "Visitor log check",
        "assessment_type": Assessment.AssessmentType.CONTROL_TEST,
        "review_date": "2026-10-07",
        "reviewer": "Facilities",
        "status": Assessment.Status.PLANNED,
        "risk": "",
        "control": control.pk,
        "outcome": "",
        "findings": "",
        "evidence": "",
        "next_review_date": "",
        "notes": "",
    }
    data.update(overrides)
    return data


class AssessmentFormPagesTests(TestCase):
    """The New and Edit pages apply the same rules as the admin screen."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.control = make_control()
        self.control.save()

    def test_empty_form_is_rejected(self):
        response = self.client.post(reverse("assessments:assessment_create"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the errors below.")
        self.assertFalse(Assessment.objects.exists())

    def test_new_assessment_asks_for_a_process_or_solution(self):
        page = self.client.get(reverse("assessments:assessment_create"))
        self.assertContains(page, "Process or solution")
        self.assertContains(page, "Show controls and risks")
        self.assertNotContains(page, "A control test names a control.")

    def test_risk_review_without_a_risk_is_rejected(self):
        review = make_assessment(
            title="Phishing review",
            assessment_type=Assessment.AssessmentType.RISK_REVIEW,
            risk=make_risk_for_links(),
            control=None,
        )
        review.save()
        data = assessment_form_data(
            self.control, assessment_type=Assessment.AssessmentType.RISK_REVIEW, risk=""
        )
        data["control"] = ""
        response = self.client.post(reverse("assessments:assessment_edit", args=[review.pk]), data)
        self.assertContains(response, "Choose the risk this review covers.")

    def test_completing_an_assessment_needs_an_outcome(self):
        assessment = make_assessment(control=self.control, title="Visitor log check")
        assessment.save()
        edit_url = reverse("assessments:assessment_edit", args=[assessment.pk])
        rejected = self.client.post(
            edit_url, assessment_form_data(self.control, status=Assessment.Status.COMPLETE)
        )
        self.assertContains(rejected, "Record the outcome when the assessment is complete.")
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, Assessment.Status.PLANNED)

        saved = self.client.post(
            edit_url,
            assessment_form_data(
                self.control,
                status=Assessment.Status.COMPLETE,
                outcome=Assessment.Outcome.PARTIAL,
                findings="The log is not always completed.",
                evidence="Sample of last week's visitor book.",
            ),
        )
        self.assertRedirects(saved, reverse("assessments:assessment_detail", args=[assessment.pk]))
        assessment.refresh_from_db()
        self.assertEqual(assessment.outcome, Assessment.Outcome.PARTIAL)
        self.assertEqual(assessment.assessment_id, "ASMT-0001")

    def test_archived_assessment_cannot_be_edited(self):
        assessment = make_assessment(control=self.control, archived_at=timezone.now())
        assessment.save()
        edit_url = reverse("assessments:assessment_edit", args=[assessment.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        response = self.client.post(edit_url, assessment_form_data(self.control, title="Changed"))
        self.assertEqual(response.status_code, 403)
        assessment.refresh_from_db()
        self.assertEqual(assessment.title, "MFA operating check")

    def test_users_without_permission_cannot_create_or_edit(self):
        assessment = make_assessment(control=self.control)
        assessment.save()
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse("assessments:assessment_create")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("assessments:assessment_edit", args=[assessment.pk])).status_code,
            403,
        )


class AssessmentArchiveTests(TestCase):
    """Archiving hides an assessment; restoring brings it back."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.control = make_control()
        self.control.save()
        self.assessment = make_assessment(
            control=self.control,
            status=Assessment.Status.COMPLETE,
            outcome=Assessment.Outcome.SATISFACTORY,
            findings="The second factor is required.",
            evidence="Sign-in screen.",
        )
        self.assessment.save()
        self.archive_url = reverse("assessments:assessment_archive", args=[self.assessment.pk])
        self.restore_url = reverse("assessments:assessment_restore", args=[self.assessment.pk])

    def test_confirmation_page_does_not_archive_yet(self):
        response = self.client.get(self.archive_url)
        self.assertContains(response, "Archive assessment")
        self.assertContains(response, "not deleted")
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.archived_at)

    def test_archive_hides_it_from_the_list_and_the_control(self):
        self.assertContains(
            self.client.get(reverse("assessments:assessment_list")), "MFA operating check"
        )
        response = self.client.post(self.archive_url)
        self.assertRedirects(response, reverse("assessments:assessment_list"))
        self.assessment.refresh_from_db()
        self.assertIsNotNone(self.assessment.archived_at)
        self.assertEqual(self.assessment.outcome, Assessment.Outcome.SATISFACTORY)
        self.assertNotContains(
            self.client.get(reverse("assessments:assessment_list")), "MFA operating check"
        )
        self.assertContains(
            self.client.get(reverse("assessments:archived_assessment_list")), "MFA operating check"
        )
        control_page = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertNotContains(control_page, "MFA operating check")

    def test_restore_brings_it_back(self):
        self.client.post(self.archive_url)
        response = self.client.post(self.restore_url, follow=True)
        self.assertRedirects(
            response, reverse("assessments:assessment_detail", args=[self.assessment.pk])
        )
        self.assertContains(response, "restored to the list")
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.archived_at)
        self.assertContains(
            self.client.get(reverse("controls:control_detail", args=[self.control.pk])),
            "MFA operating check",
        )

    def test_archived_detail_shows_restore_not_edit(self):
        self.client.post(self.archive_url)
        response = self.client.get(
            reverse("assessments:assessment_detail", args=[self.assessment.pk])
        )
        self.assertContains(response, "read-only until it is restored")
        self.assertContains(response, ">Restore</button>")
        self.assertNotContains(response, ">Edit</a>")

    def test_restore_only_accepts_form_submissions(self):
        self.client.post(self.archive_url)
        self.assertEqual(self.client.get(self.restore_url).status_code, 405)
        self.assessment.refresh_from_db()
        self.assertIsNotNone(self.assessment.archived_at)

    def test_users_without_permission_cannot_archive_or_restore(self):
        reader = get_user_model().objects.create_user(username="reader", password="x-Long-pw-123")
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.archive_url).status_code, 403)
        self.assessment.refresh_from_db()
        self.assertIsNone(self.assessment.archived_at)

        self.client.force_login(self.user)
        self.client.post(self.archive_url)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(self.restore_url).status_code, 403)
        archive_page = self.client.get(reverse("assessments:archived_assessment_list"))
        self.assertContains(archive_page, "MFA operating check")
        self.assertNotContains(archive_page, ">Restore</button>")


def _risk_post(prefix, risk, **overrides):
    """
    Build the register fields for one risk line.

    Inputs: the form prefix (for example "risks-0"), the risk, and any
    fields to change. Output: a dictionary the test client can post.
    """
    data = {
        f"{prefix}-title": risk.title,
        f"{prefix}-description": risk.description,
        f"{prefix}-category": risk.category_id,
        f"{prefix}-owner": risk.owner,
        f"{prefix}-risk_source": risk.risk_source,
        f"{prefix}-date_identified": risk.date_identified.isoformat() if risk.date_identified else "",
        f"{prefix}-inherent_likelihood": risk.inherent_likelihood,
        f"{prefix}-inherent_impact": risk.inherent_impact,
        f"{prefix}-residual_likelihood": risk.residual_likelihood or "",
        f"{prefix}-residual_impact": risk.residual_impact or "",
        f"{prefix}-status": risk.status,
        f"{prefix}-response_type": risk.response_type,
        f"{prefix}-response_description": risk.response_description,
        f"{prefix}-accepted_by": risk.accepted_by,
        f"{prefix}-acceptance_date": risk.acceptance_date.isoformat() if risk.acceptance_date else "",
        f"{prefix}-acceptance_expiry_date": (
            risk.acceptance_expiry_date.isoformat() if risk.acceptance_expiry_date else ""
        ),
        f"{prefix}-notes": risk.notes,
        f"{prefix}-findings": "Reviewed.",
        f"{prefix}-evidence": "Notes from the meeting.",
    }
    data.update(overrides)
    return data


class ProcessReviewTests(TestCase):
    """A process review creates, updates or closes risks only as the lines say."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="w", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.category = RiskCategory.objects.create(name="Cyber")
        self.process = Process.objects.create(
            kind=Process.Kind.SOLUTION,
            name="Email",
            description="Staff email.",
            owner="IT manager",
        )
        self.control = make_control()
        self.control.save()
        ProcessControl.objects.create(process=self.process, control=self.control)

    def post_review(self, **overrides):
        """Post a complete review. Input: fields to change. Output: the response."""
        data = {
            "process": self.process.pk,
            "loaded_process": self.process.pk,
            "title": "Email review",
            "review_date": "2026-10-07",
            "reviewer": "Internal audit",
            "status": Assessment.Status.COMPLETE,
            "next_review_date": "",
            "notes": "",
            "controls-TOTAL_FORMS": "1",
            "controls-INITIAL_FORMS": "0",
            "controls-MIN_NUM_FORMS": "0",
            "controls-MAX_NUM_FORMS": "1000",
            "controls-0-control_id": self.control.pk,
            "controls-0-include": "on",
            "controls-0-outcome": Assessment.Outcome.UNSATISFACTORY,
            "controls-0-findings": "The second factor was not required.",
            "controls-0-evidence": "Walkthrough of the sign-in screen.",
            "controls-0-likelihood": "3",
            "controls-0-impact": "4",
            "controls-0-category": self.category.pk,
            "risks-TOTAL_FORMS": "0",
            "risks-INITIAL_FORMS": "0",
            "risks-MIN_NUM_FORMS": "0",
            "risks-MAX_NUM_FORMS": "1000",
            "new_risks-TOTAL_FORMS": "0",
            "new_risks-INITIAL_FORMS": "0",
            "new_risks-MIN_NUM_FORMS": "0",
            "new_risks-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return self.client.post(
            reverse("assessments:process_review_create", args=[self.process.pk]), data
        )

    def test_unsatisfactory_creates_an_open_risk(self):
        response = self.post_review()
        risk = Risk.objects.get()
        self.assertRedirects(response, reverse("assessments:assessment_detail", args=[Assessment.objects.get().pk]))
        self.assertEqual(risk.process, self.process)
        self.assertEqual(risk.inherent_score, 12)
        self.assertEqual(risk.status, Risk.Status.OPEN)
        self.assertEqual(risk.description, "The second factor was not required.")
        link = risk.control_links.get()
        self.assertEqual(link.control, self.control)
        self.assertEqual(link.effectiveness, RiskControl.Effectiveness.INEFFECTIVE)
        page = self.client.get(reverse("processes:process_detail", args=[self.process.pk]))
        self.assertContains(page, risk.risk_id)
        assessment = Assessment.objects.get()
        risk_page = self.client.get(reverse("risks:risk_detail", args=[risk.pk]))
        self.assertContains(risk_page, assessment.assessment_id)
        self.assertContains(risk_page, "Unsatisfactory")
        control_page = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(control_page, assessment.assessment_id)
        self.assertContains(control_page, "Unsatisfactory")

    def test_a_later_review_updates_that_risk(self):
        self.post_review()
        first = Risk.objects.get()
        self.post_review(**{
            "title": "Email review follow-up",
            "controls-0-outcome": Assessment.Outcome.PARTIAL,
            "controls-0-findings": "The second factor is only required for remote access.",
            "controls-0-likelihood": "2",
            "controls-0-impact": "2",
            "controls-0-category": "",
        })
        self.assertEqual(Risk.objects.count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.inherent_score, 4)
        self.assertEqual(first.description, "The second factor is only required for remote access.")
        self.assertEqual(
            first.control_links.get().effectiveness, RiskControl.Effectiveness.PARTIAL
        )

    def test_satisfactory_does_not_create_or_close_a_risk(self):
        existing = make_risk(self.category, process=self.process, title="Existing phishing risk")
        existing.save()
        RiskControl.objects.create(
            risk=existing, control=self.control,
            effectiveness=RiskControl.Effectiveness.EFFECTIVE,
        )
        self.post_review(**{
            "controls-0-outcome": Assessment.Outcome.SATISFACTORY,
            "controls-0-findings": "The second factor is required.",
            "controls-0-evidence": "Walkthrough of the sign-in screen.",
            "controls-0-likelihood": "",
            "controls-0-impact": "",
            "controls-0-category": "",
        })
        self.assertEqual(Risk.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.status, Risk.Status.OPEN)
        self.assertEqual(existing.title, "Existing phishing risk")

    def test_a_planned_review_does_not_create_a_risk(self):
        self.post_review(status=Assessment.Status.PLANNED)
        self.assertFalse(Risk.objects.exists())
        self.assertEqual(Assessment.objects.get().status, Assessment.Status.PLANNED)

    def test_a_failed_control_needs_scores(self):
        response = self.post_review(**{
            "controls-0-likelihood": "",
            "controls-0-impact": "",
        })
        self.assertContains(response, "A risk cannot be saved without both.")
        self.assertFalse(Risk.objects.exists())

    def test_reassessing_can_close_a_risk_without_changing_its_score(self):
        existing = make_risk(
            self.category, process=self.process, title="Existing phishing risk",
            residual_likelihood=2, residual_impact=2,
        )
        existing.save()
        response = self.post_review(**{
            "controls-TOTAL_FORMS": "0",
            **_risk_post("risks-0", existing),
            "risks-TOTAL_FORMS": "1",
            "risks-0-risk_id": existing.pk,
            "risks-0-include": "on",
            "risks-0-findings": "The exposure has been removed.",
            "risks-0-evidence": "The mailbox is no longer in use.",
            "risks-0-status": Risk.Status.CLOSED,
        })
        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.status, Risk.Status.CLOSED)
        self.assertEqual(existing.inherent_score, 12)
        self.assertEqual(existing.residual_score, 4)
        self.assertEqual(existing.description, "Made-up test risk.")
        self.assertEqual(
            existing.changes.filter(field_name="Status").get().new_value, "Closed"
        )
        risk_page = self.client.get(reverse("risks:risk_detail", args=[existing.pk]))
        self.assertContains(risk_page, "Closed")
        self.assertContains(risk_page, "Email review")

    def test_a_control_left_out_is_not_shown_on_its_page(self):
        other = make_control(title="Offline backups")
        other.save()
        ProcessControl.objects.create(process=self.process, control=other)
        self.post_review(**{
            "controls-TOTAL_FORMS": "2",
            "controls-1-control_id": other.pk,
            "controls-1-include": "",
            "controls-1-outcome": "",
            "controls-1-findings": "",
            "controls-1-evidence": "",
            "controls-1-likelihood": "",
            "controls-1-impact": "",
            "controls-1-category": "",
        })
        other_page = self.client.get(reverse("controls:control_detail", args=[other.pk]))
        self.assertNotContains(other_page, "Email review")
        included_page = self.client.get(reverse("controls:control_detail", args=[self.control.pk]))
        self.assertContains(included_page, "Email review")

    def test_new_assessment_lists_every_current_risk_after_the_solution_is_chosen(self):
        other = make_risk(self.category, process=self.process, title="Lost laptop")
        other.save()
        page = self.client.post(reverse("assessments:assessment_create"), {
            "process": self.process.pk,
            "title": "Email review",
            "review_date": "2026-10-07",
            "reviewer": "Internal audit",
            "status": Assessment.Status.PLANNED,
            "show_lines": "1",
        })
        self.assertContains(page, self.control.title)
        self.assertContains(page, "Lost laptop")
        self.assertContains(page, "Inherent likelihood")
        self.assertContains(page, "Add another risk")
        self.assertFalse(Assessment.objects.exists())

    def test_a_ticked_risk_can_be_updated_from_the_assessment(self):
        existing = make_risk(self.category, process=self.process, title="Existing phishing risk")
        existing.save()
        self.post_review(**{
            "controls-TOTAL_FORMS": "0",
            "risks-TOTAL_FORMS": "1",
            **_risk_post(
                "risks-0", existing,
                **{
                    "risks-0-risk_id": existing.pk,
                    "risks-0-include": "on",
                    "risks-0-title": "Phishing via email",
                    "risks-0-owner": "Security lead",
                },
            ),
        })
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Phishing via email")
        self.assertEqual(existing.owner, "Security lead")
        self.assertEqual(existing.process, self.process)
        self.assertEqual(
            existing.changes.filter(field_name="Title").get().new_value, "Phishing via email"
        )

    def test_a_new_risk_can_be_added_from_the_assessment(self):
        self.post_review(**{
            "controls-TOTAL_FORMS": "0",
            "new_risks-TOTAL_FORMS": "1",
            **_risk_post(
                "new_risks-0",
                make_risk(self.category, process=self.process, title="Unused"),
                **{
                    "new_risks-0-title": "Mailbox misconfiguration",
                    "new_risks-0-description": "Shared mailboxes have no owner.",
                    "new_risks-0-findings": "No owner is recorded.",
                    "new_risks-0-evidence": "The mailbox list.",
                },
            ),
        })
        created = Risk.objects.get(title="Mailbox misconfiguration")
        self.assertEqual(created.process, self.process)
        self.assertEqual(created.description, "Shared mailboxes have no owner.")
        self.assertEqual(created.inherent_score, 12)

    def test_the_list_counts_included_control_outcomes(self):
        other = make_control(title="Offline backups")
        other.save()
        left_out = make_control(title="Visitor log")
        left_out.save()
        self.post_review()
        assessment = Assessment.objects.get()
        AssessedControl.objects.create(
            assessment=assessment,
            control=other,
            include=True,
            outcome=Assessment.Outcome.SATISFACTORY,
            findings="Backups ran.",
            evidence="The last backup log.",
        )
        AssessedControl.objects.create(
            assessment=assessment,
            control=left_out,
            include=False,
            outcome=Assessment.Outcome.UNSATISFACTORY,
        )
        listing = self.client.get(reverse("assessments:assessment_list"))
        self.assertContains(listing, "1 unsatisfactory, 1 satisfactory")
        self.assertNotContains(listing, "2 unsatisfactory")
