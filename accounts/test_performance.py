"""Repeatable, local-only measurements for the SRS authentication scenarios."""

import json
import re
import time
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import SMSOTPDeliveryLimit, User


class SRSAuthenticationPerformanceTests(TestCase):
    """Measure complete server-side flows with fictional accounts and local providers."""

    @classmethod
    def setUpTestData(cls):
        password = "FictionalDemo!2468"
        cls.users = {
            User.Role.STUDENT: User.objects.create_user(
                "perf-student@example.test", password, full_name="Performance Student",
                role=User.Role.STUDENT, phone_number="+15550100001",
            ),
            User.Role.TEACHER: User.objects.create_user(
                "perf-teacher@example.test", password, full_name="Performance Teacher",
                role=User.Role.TEACHER, phone_number="+15550100002",
            ),
            User.Role.ADMIN: User.objects.create_superuser(
                "perf-admin@example.test", password, full_name="Performance Administrator",
                phone_number="+15550100003",
            ),
        }
        cls.password = password

    def _record(self, role, runs):
        timings = [round(value, 2) for value in runs]
        result = {"role": role, "runs_ms": timings, "mean_ms": round(sum(runs) / len(runs), 2)}
        print("SRS_PERFORMANCE " + json.dumps(result, sort_keys=True))
        return result

    def _email_code(self):
        match = re.search(r"(?m)^([0-9]{6})$", mail.outbox[-1].body)
        self.assertIsNotNone(match, "The local email provider did not expose a six-digit test code.")
        return match.group(1)

    @override_settings(
        AUTHSHIELD_LOGIN_ENABLED=True,
        AUTHSHIELD_BASELINE_LOGIN_ENABLED=True,
        AUTHSHIELD_OTP_ENABLED=False,
        AUTHSHIELD_KEYCLOAK_ENABLED=False,
        AUTHSHIELD_FIREBASE_API_KEY="",
        AUTHSHIELD_FIREBASE_AUTH_DOMAIN="",
        AUTHSHIELD_FIREBASE_PROJECT_ID="",
        AUTHSHIELD_FIREBASE_APP_ID="",
        AUTHSHIELD_GMAIL_ADDRESS="authshield-test@example.test",
        AUTHSHIELD_GMAIL_APP_PASSWORD="test-app-password",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_password_only_baseline_three_runs_per_role(self):
        results = []
        for role, user in self.users.items():
            runs = []
            for _ in range(3):
                mail.outbox.clear()
                browser = Client()
                started = time.perf_counter()
                response = browser.post(reverse("login"), {
                    "username": user.email, "password": self.password,
                })
                if role == User.Role.ADMIN:
                    self.assertRedirects(response, reverse("otp_verify"), fetch_redirect_response=False)
                    self.assertNotIn("_auth_user_id", browser.session)
                    response = browser.post(reverse("otp_verify"), {"code": self._email_code()})
                self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
                runs.append((time.perf_counter() - started) * 1000)
            label = "admin (mandatory email OTP)" if role == User.Role.ADMIN else role
            results.append(self._record(label, runs))
        self.assertEqual(len(results), 3)

    @override_settings(
        AUTHSHIELD_LOGIN_ENABLED=True,
        AUTHSHIELD_BASELINE_LOGIN_ENABLED=True,
        AUTHSHIELD_OTP_ENABLED=True,
        AUTHSHIELD_EMAIL_STEP_UP=False,
        AUTHSHIELD_KEYCLOAK_ENABLED=False,
        AUTHSHIELD_FIREBASE_API_KEY="",
        AUTHSHIELD_FIREBASE_AUTH_DOMAIN="",
        AUTHSHIELD_FIREBASE_PROJECT_ID="",
        AUTHSHIELD_FIREBASE_APP_ID="",
        AUTHSHIELD_GMAIL_ADDRESS="authshield-test@example.test",
        AUTHSHIELD_GMAIL_APP_PASSWORD="test-app-password",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_password_plus_email_otp_three_runs_per_role(self):
        results = []
        for role, user in self.users.items():
            runs = []
            for _ in range(3):
                mail.outbox.clear()
                browser = Client()
                started = time.perf_counter()
                first = browser.post(reverse("login"), {
                    "username": user.email, "password": self.password, "otp_channel": "email",
                })
                self.assertRedirects(first, reverse("otp_verify"), fetch_redirect_response=False)
                second = browser.post(reverse("otp_verify"), {"code": self._email_code()})
                self.assertRedirects(second, reverse("dashboard"), fetch_redirect_response=False)
                runs.append((time.perf_counter() - started) * 1000)
            results.append(self._record(role, runs))
        self.assertEqual(len(results), 3)

    @override_settings(
        AUTHSHIELD_LOGIN_ENABLED=True,
        AUTHSHIELD_BASELINE_LOGIN_ENABLED=True,
        AUTHSHIELD_OTP_ENABLED=True,
        AUTHSHIELD_EMAIL_STEP_UP=True,
        AUTHSHIELD_KEYCLOAK_ENABLED=False,
        AUTHSHIELD_FIREBASE_API_KEY="test-web-api-key",
        AUTHSHIELD_FIREBASE_AUTH_DOMAIN="authshield-test.firebaseapp.com",
        AUTHSHIELD_FIREBASE_PROJECT_ID="authshield-test",
        AUTHSHIELD_FIREBASE_APP_ID="1:123:web:test",
        AUTHSHIELD_GMAIL_ADDRESS="authshield-test@example.test",
        AUTHSHIELD_GMAIL_APP_PASSWORD="test-app-password",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_sms_then_email_step_up_three_runs_per_role(self):
        results = []
        firebase_claims = {"phone_number": "", "firebase": {"sign_in_provider": "phone"}}
        with patch("accounts.views.verify_firebase_phone_id_token", return_value=firebase_claims):
            for role, user in self.users.items():
                runs = []
                for run in range(3):
                    mail.outbox.clear()
                    if run:
                        limit = SMSOTPDeliveryLimit.objects.get(user=user)
                        limit.last_requested_at -= timedelta(seconds=61)
                        limit.save(update_fields=("last_requested_at",))
                    browser = Client()
                    started = time.perf_counter()
                    first = browser.post(reverse("login"), {
                        "username": user.email, "password": self.password, "otp_channel": "sms",
                    })
                    self.assertRedirects(first, reverse("otp_verify"), fetch_redirect_response=False)
                    self.assertEqual(browser.post(reverse("otp_sms_authorize_send")).status_code, 200)
                    self.assertEqual(browser.post(reverse("otp_sms_mark_sent")).status_code, 200)
                    sms_verified = browser.post(reverse("otp_verify"), {
                        "code": "123456", "firebase_id_token": "signed-test-token",
                    })
                    self.assertRedirects(sms_verified, reverse("otp_verify"), fetch_redirect_response=False)
                    email_verified = browser.post(reverse("otp_verify"), {"code": self._email_code()})
                    self.assertRedirects(email_verified, reverse("dashboard"), fetch_redirect_response=False)
                    runs.append((time.perf_counter() - started) * 1000)
                results.append(self._record(role, runs))
        self.assertEqual(len(results), 3)
