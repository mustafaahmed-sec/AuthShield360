import hashlib

from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
        self.assertEqual(event.auth_mode, "password")
        self.assertEqual(event.factor, "password")
        self.assertEqual(event.outcome, "success")
        self.assertEqual(event.ip_address, "127.0.0.1")
        self.assertIsNotNone(event.duration_ms)
        session_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(event.session_hint, hashlib.sha256(session_cookie.encode()).hexdigest()[:8])

    def test_failed_login_is_logged_without_recording_password(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email, "password": "incorrect-password",
        })
        self.assertEqual(response.status_code, 200)
        event = PortalAuditEvent.objects.get(action="login_failure")
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_email, self.user.email)
        self.assertNotIn("incorrect-password", event.description)
        self.assertEqual(event.outcome, "failure")
        self.assertEqual(event.factor, "password")
        self.assertEqual(event.ip_address, "127.0.0.1")


@override_settings(
    AUTHSHIELD_LOCKOUT_ATTEMPTS=5,
    AUTHSHIELD_LOCKOUT_WINDOW_MINUTES=15,
    AUTHSHIELD_LOCKOUT_MINUTES=15,
    AUTHSHIELD_IP_FAILURE_LIMIT=30,
    AUTHSHIELD_IP_WINDOW_MINUTES=15,
    AUTHSHIELD_IP_THROTTLE_MINUTES=1,
)
class FailedLoginProtectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "lockout-student@example.test", "FictionalDemo!2468",
            full_name="Lockout Student", role=User.Role.STUDENT,
        )

    def post_login(self, email=None, password="wrong-password", **extra):
        return self.client.post(
            reverse("login"),
            {"username": email or self.user.email, "password": password},
            **extra,
        )

    def test_five_failures_start_fifteen_minute_lock_and_later_attempt_is_blocked(self):
        for _ in range(5):
            response = self.post_login()
            self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertGreater(self.user.locked_until, timezone.now())
        self.assertEqual(PortalAuditEvent.objects.filter(action="login_failure").count(), 5)
        self.assertEqual(PortalAuditEvent.objects.filter(action="locked_out").count(), 1)

        blocked = self.post_login(password="FictionalDemo!2468")
        self.assertContains(blocked, "Too many attempts. Try again in 15 minutes.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(PortalAuditEvent.objects.filter(action="locked_out").count(), 2)

    def test_successful_login_resets_failure_counter(self):
        for _ in range(4):
            self.post_login()

        success = self.post_login(password="FictionalDemo!2468")
        self.assertEqual(success.status_code, 302)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.post_login()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)

    def test_admin_unlock_action_clears_lock_and_records_who_unlocked_it(self):
        admin = User.objects.create_superuser(
            "unlock-admin@example.test", "AdminDemo!2468", full_name="Unlock Administrator",
        )
        self.user.locked_until = timezone.now() + timedelta(minutes=10)
        self.user.save(update_fields=("locked_until",))
        self.client.force_login(admin)

        response = self.client.post(reverse("admin:accounts_user_changelist"), {
            "action": "unlock_selected_accounts",
            "_selected_action": [str(self.user.pk)],
            "index": "0",
        })

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        event = PortalAuditEvent.objects.get(action="account_unlocked")
        self.assertEqual(event.actor, admin)
        self.assertEqual(event.target_name, self.user.email)
        self.assertEqual(event.factor, PortalAuditEvent.Factor.ACCESS)

        self.post_login()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)

    def test_status_lookup_uses_the_same_account_lockout(self):
        pending = User.objects.create_user(
            "pending-lockout@example.test", "FictionalDemo!2468", full_name="Pending Student",
            role=User.Role.STUDENT, approval_status=User.ApprovalStatus.PENDING, is_active=False,
        )
        status_data = {"email": pending.email, "password": "incorrect"}
        for _ in range(5):
            self.client.post(reverse("registration_status"), status_data)

        pending.refresh_from_db()
        self.assertGreater(pending.locked_until, timezone.now())
        blocked = self.client.post(reverse("registration_status"), {
            "email": pending.email, "password": "FictionalDemo!2468",
        })
        self.assertContains(blocked, "Too many attempts.")
        self.assertNotContains(blocked, "Waiting for review")
        self.assertEqual(
            PortalAuditEvent.objects.filter(action="registration_status_failure").count(), 5
        )

    @override_settings(
        AUTHSHIELD_LOCKOUT_ATTEMPTS=100,
        AUTHSHIELD_IP_FAILURE_LIMIT=2,
        AUTHSHIELD_IP_WINDOW_MINUTES=15,
        AUTHSHIELD_IP_THROTTLE_MINUTES=2,
    )
    def test_ip_throttle_applies_across_multiple_submitted_emails(self):
        for email in ("unknown-one@example.test", "unknown-two@example.test"):
            self.post_login(email=email, REMOTE_ADDR="192.0.2.40")

        blocked = self.post_login(email="unknown-three@example.test", REMOTE_ADDR="192.0.2.40")

        form = blocked.context["form"]
        error_codes = [
            error.code
            for errors in form.errors.as_data().values()
            for error in errors
        ]
        self.assertContains(blocked, "Too many attempts. Try again in 2 minutes.")
        self.assertEqual(error_codes, ["ip_rate_limited"])
        self.assertEqual(PortalAuditEvent.objects.filter(action="ip_rate_limited").count(), 1)
