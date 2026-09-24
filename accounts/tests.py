from django.test import TestCase
from django.urls import reverse

from school.models import PortalAuditEvent, StudentRecord

from .models import User


class PublicAccountFlowTests(TestCase):
    def test_approved_account_can_sign_in_and_bad_password_is_rejected(self):
        user = User.objects.create_user(
            "teacher@example.test", "FictionalDemo!2468", full_name="Demo Teacher", role=User.Role.TEACHER
        )
        bad = self.client.post(reverse("login"), {"username": user.email, "password": "incorrect"})
        self.assertEqual(bad.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        good = self.client.post(reverse("login"), {"username": user.email, "password": "FictionalDemo!2468"})
        self.assertRedirects(good, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_status_lookup_requires_the_matching_password(self):
        user = User.objects.create_user(
            "pending@example.test", "FictionalDemo!2468", full_name="Pending Student",
            role=User.Role.STUDENT, approval_status=User.ApprovalStatus.PENDING, is_active=False,
        )
        url = reverse("registration_status")
        pending = self.client.post(url, {"email": user.email, "password": "FictionalDemo!2468"})
        self.assertContains(pending, "Waiting for review")
        wrong = self.client.post(url, {"email": user.email, "password": "incorrect"})
        unknown = self.client.post(url, {"email": "unknown@example.test", "password": "incorrect"})
        self.assertContains(wrong, "We could not check this request")
        self.assertContains(unknown, "We could not check this request")
        self.assertNotContains(wrong, "Waiting for review")

    def test_duplicate_approved_email_has_generic_signup_error(self):
        User.objects.create_user(
            "existing@example.test", "FictionalDemo!2468", full_name="Existing Student", role=User.Role.STUDENT
        )
        response = self.client.post(reverse("student_signup"), {
            "full_name": "Someone Else", "email": "existing@example.test", "phone_number": "+1 555 010 0100",
            "password1": "FictionalDemo!2468-Strong", "password2": "FictionalDemo!2468-Strong",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not submit this request")
        self.assertEqual(User.objects.filter(email="existing@example.test").count(), 1)

    def test_rejected_applicant_can_resubmit_and_admin_can_approve(self):
        admin = User.objects.create_superuser("reviewer@example.test", "AdminDemo!2468", full_name="Reviewer")
        applicant = User.objects.create_user(
            "rejected@example.test", "FictionalDemo!2468-Strong", full_name="Former Applicant",
            role=User.Role.STUDENT, approval_status=User.ApprovalStatus.REJECTED, is_active=False, reviewed_by=admin,
        )
        response = self.client.post(reverse("student_signup"), {
            "full_name": "Updated Applicant", "email": applicant.email, "phone_number": "+1 555 010 0101",
            "password1": "FictionalDemo!2468-Strong", "password2": "FictionalDemo!2468-Strong",
        })
        self.assertRedirects(response, reverse("registration_status"))
        applicant.refresh_from_db()
        self.assertEqual(applicant.full_name, "Updated Applicant")
        self.assertEqual(applicant.approval_status, User.ApprovalStatus.PENDING)
        self.assertIsNone(applicant.reviewed_by)
        self.assertFalse(applicant.is_active)
        self.client.force_login(admin)
        self.client.post(reverse("review_account_request", args=[applicant.pk]), {"action": "reject"})
        response = self.client.post(reverse("review_account_request", args=[applicant.pk]), {"action": "approve"})
        self.assertRedirects(response, reverse("admin_management"))
        applicant.refresh_from_db()
        self.assertTrue(applicant.is_active)
        self.assertTrue(StudentRecord.objects.filter(student=applicant).exists())


class AuthenticationAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "student@example.test", "FictionalDemo!2468", full_name="Test Student", role=User.Role.STUDENT
        )

    def test_successful_login_is_audit_logged(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email, "password": "FictionalDemo!2468",
        })
        self.assertEqual(response.status_code, 302)
        event = PortalAuditEvent.objects.get(action="login_success")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_role, User.Role.STUDENT)

    def test_failed_login_is_logged_without_recording_password(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email, "password": "incorrect-password",
        })
        self.assertEqual(response.status_code, 200)
        event = PortalAuditEvent.objects.get(action="login_failure")
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_email, self.user.email)
        self.assertNotIn("incorrect-password", event.description)
