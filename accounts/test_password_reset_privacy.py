from datetime import timedelta
import re
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from school.models import PortalAuditEvent

from .models import EmailOTPChallenge, PublicRequestThrottle, User


@override_settings(
    AUTHSHIELD_KEYCLOAK_ENABLED=False,
    AUTHSHIELD_GMAIL_ADDRESS="authshield-test@example.test",
    AUTHSHIELD_GMAIL_APP_PASSWORD="test-app-password",
    AUTHSHIELD_PASSWORD_RESET_RESPONSE_FLOOR_SECONDS=0,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PasswordResetPrivacyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "reset-eligible@example.test",
            "FictionalDemo!2468",
            full_name="Reset Eligible",
            role=User.Role.STUDENT,
        )
        sent_at = timezone.now() - timedelta(seconds=60)
        EmailOTPChallenge.objects.create(
            user=self.user,
            purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
            code_hash=make_password("123456"),
            sent_at=sent_at,
            expires_at=sent_at + timedelta(seconds=300),
        )

    def _begin_reset(self, client, email):
        response = client.post(
            reverse("password_reset_request"),
            {"email": email},
            REMOTE_ADDR="192.0.2.10" if client is self.client else "192.0.2.11",
        )
        self.assertRedirects(
            response,
            reverse("password_reset_verify"),
            fetch_redirect_response=False,
        )
        return client.session

    def test_verify_page_shows_generic_resend_cooldown_not_challenge_expiry(self):
        eligible_session = self._begin_reset(self.client, self.user.email)
        unknown_client = Client()
        unknown_session = self._begin_reset(unknown_client, "unknown@example.test")

        ttl = 300
        for session in (eligible_session, unknown_session):
            sent_at = session["authshield_password_reset_sent_at"]
            response = self.client.get(reverse("password_reset_verify")) if session is eligible_session else unknown_client.get(reverse("password_reset_verify"))
            self.assertEqual(response.context["otp_resend_available_at"] - sent_at, ttl)
            self.assertNotIn("otp_expires_at", response.context)
            self.assertNotContains(response, "data-expires-at=")
            self.assertContains(response, "data-reset-resend-countdown")

        self.assertTrue(
            self.user.email_otp_challenges.get(
                purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET
            ).expires_at
        )

    def test_valid_email_code_still_resets_the_password(self):
        user = User.objects.create_user(
            "fresh-reset@example.test",
            "FictionalDemo!2468",
            full_name="Fresh Reset",
            role=User.Role.STUDENT,
        )
        client = Client()
        response = client.post(
            reverse("password_reset_request"),
            {"email": user.email},
            REMOTE_ADDR="192.0.2.12",
        )
        self.assertRedirects(
            response,
            reverse("password_reset_verify"),
            fetch_redirect_response=False,
        )
        code_match = re.search(r"(?m)^([0-9]{6})$", mail.outbox[-1].body)
        self.assertIsNotNone(code_match)

        response = client.post(
            reverse("password_reset_verify"),
            {
                "code": code_match.group(1),
                "new_password1": "FreshPortal!Password2468",
                "new_password2": "FreshPortal!Password2468",
            },
        )

        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password("FreshPortal!Password2468"))

    def test_reset_email_quota_survives_new_sessions_and_resend_requests(self):
        mail.outbox.clear()
        user = User.objects.create_user(
            "quota-reset@example.test",
            "FictionalDemo!2468",
            full_name="Quota Reset",
            role=User.Role.STUDENT,
        )
        first_client = Client()
        first = first_client.post(
            reverse("password_reset_request"),
            {"email": user.email},
            REMOTE_ADDR="192.0.2.31",
        )
        self.assertRedirects(first, reverse("password_reset_verify"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)

        challenge = EmailOTPChallenge.objects.get(
            user=user,
            purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
        )
        challenge.sent_at = timezone.now() - timedelta(minutes=6)
        challenge.expires_at = challenge.sent_at + timedelta(minutes=5)
        challenge.save(update_fields=("sent_at", "expires_at"))
        resent = first_client.post(reverse("password_reset_resend"), REMOTE_ADDR="192.0.2.31")
        self.assertRedirects(resent, reverse("password_reset_verify"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 2)

        challenge.refresh_from_db()
        challenge.sent_at = timezone.now() - timedelta(minutes=6)
        challenge.expires_at = challenge.sent_at + timedelta(minutes=5)
        challenge.save(update_fields=("sent_at", "expires_at"))
        second_client = Client()
        second = second_client.post(
            reverse("password_reset_request"),
            {"email": user.email},
            REMOTE_ADDR="192.0.2.32",
        )
        self.assertRedirects(second, reverse("password_reset_verify"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 3)

        challenge.refresh_from_db()
        challenge.sent_at = timezone.now() - timedelta(minutes=6)
        challenge.expires_at = challenge.sent_at + timedelta(minutes=5)
        challenge.save(update_fields=("sent_at", "expires_at"))
        third_client = Client()
        blocked = third_client.post(
            reverse("password_reset_request"),
            {"email": user.email},
            REMOTE_ADDR="192.0.2.33",
        )
        self.assertRedirects(blocked, reverse("password_reset_verify"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 3)
        bucket = PublicRequestThrottle.objects.get(purpose="password-reset-account")
        self.assertEqual(bucket.request_count, 3)
        self.assertNotIn(user.email, bucket.fingerprint)
        self.assertEqual(
            PortalAuditEvent.objects.filter(
                actor=user,
                action="password_reset_otp_sent",
            ).count(),
            3,
        )

    def test_malformed_reset_code_does_not_enter_password_hash_check(self):
        session = self.client.session
        session["authshield_password_reset_user_id"] = self.user.pk
        session["authshield_password_reset_started_at"] = timezone.now().timestamp()
        session.save()

        with patch("accounts.views.check_password") as check_password:
            response = self.client.post(
                reverse("password_reset_verify"),
                {"code": "1" * 2048},
            )

        self.assertEqual(response.status_code, 200)
        check_password.assert_not_called()
        challenge = EmailOTPChallenge.objects.get(
            user=self.user,
            purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
        )
        self.assertEqual(challenge.attempts, 1)

    def test_resend_feedback_and_timer_are_generic_for_eligible_and_unknown_email(self):
        eligible_session = self._begin_reset(self.client, self.user.email)
        unknown_client = Client()
        unknown_session = self._begin_reset(unknown_client, "unknown@example.test")

        eligible_response = self.client.post(reverse("password_reset_resend"))
        unknown_response = unknown_client.post(reverse("password_reset_resend"))
        for response in (eligible_response, unknown_response):
            self.assertRedirects(
                response,
                reverse("password_reset_verify"),
                fetch_redirect_response=False,
            )

        eligible_session = self.client.session
        unknown_session = unknown_client.session
        eligible_page = self.client.get(reverse("password_reset_verify"))
        unknown_page = unknown_client.get(reverse("password_reset_verify"))
        self.assertEqual(
            eligible_page.context["otp_resend_available_at"]
            - eligible_session["authshield_password_reset_sent_at"],
            300,
        )
        self.assertEqual(
            unknown_page.context["otp_resend_available_at"]
            - unknown_session["authshield_password_reset_sent_at"],
            300,
        )
        self.assertEqual(eligible_session["authshield_password_reset_resends"], 1)
        self.assertEqual(unknown_session["authshield_password_reset_resends"], 1)

        self.assertEqual(
            [str(message) for message in eligible_page.context["messages"]],
            [str(message) for message in unknown_page.context["messages"]],
        )
        self.assertEqual(len(mail.outbox), 0)
