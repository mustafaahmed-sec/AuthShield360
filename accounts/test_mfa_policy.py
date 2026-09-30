from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .keycloak import KeycloakAdminError, keycloak_set_totp_required
from .mfa import policy_for_user
from .models import EmailOTPChallenge, RoleMFAPolicy, User
from school.models import PortalAuditEvent


@override_settings(
    AUTHSHIELD_LOGIN_ENABLED=True,
    AUTHSHIELD_KEYCLOAK_ENABLED=False,
    AUTHSHIELD_OTP_ENABLED=False,
    AUTHSHIELD_EMAIL_STEP_UP=False,
    AUTHSHIELD_OTP_EXEMPT_EMAILS=frozenset(),
    AUTHSHIELD_FIREBASE_API_KEY="",
    AUTHSHIELD_FIREBASE_AUTH_DOMAIN="",
    AUTHSHIELD_FIREBASE_PROJECT_ID="",
    AUTHSHIELD_FIREBASE_APP_ID="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AdminMFAPolicyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "mfa-admin@example.test", "FictionalAdmin!2468", full_name="MFA Administrator"
        )
        self.student = User.objects.create_user(
            "mfa-student@example.test", "FictionalStudent!2468", full_name="MFA Student",
            role=User.Role.STUDENT,
        )
        self.client.force_login(self.admin)

    def _all_roles_post(self, *, student_enabled=False, confirm=True):
        data = {
            "student-enabled": "on" if student_enabled else "",
            "student-sms_enabled": "",
            "student-email_enabled": "on" if student_enabled else "",
            "student-require_both_factors": "",
            "teacher-enabled": "",
            "teacher-sms_enabled": "",
            "teacher-email_enabled": "",
            "teacher-require_both_factors": "",
            "admin-enabled": "",
            "admin-sms_enabled": "",
            "admin-email_enabled": "",
            "admin-require_both_factors": "",
            "keycloak-totp_enabled": "",
            "confirm": "on" if confirm else "",
        }
        return self.client.post(reverse("admin_mfa_settings"), data)

    def test_admin_can_open_settings_and_non_admin_is_denied(self):
        response = self.client.get(reverse("admin_mfa_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student accounts")
        self.assertContains(response, "Firebase SMS OTP")
        self.assertContains(response, "Keycloak authenticator app (TOTP)")
        self.assertContains(response, "always need a second-factor code")

        self.client.force_login(self.student)
        denied = self.client.get(reverse("admin_mfa_settings"))
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(PortalAuditEvent.objects.filter(action="role_access_denied").exists())

    def test_policy_requires_confirmation_and_audits_successful_save(self):
        missing_confirmation = self._all_roles_post(student_enabled=True, confirm=False)
        self.assertEqual(missing_confirmation.status_code, 200)
        self.assertFalse(RoleMFAPolicy.objects.get(role=User.Role.STUDENT).enabled)

        response = self._all_roles_post(student_enabled=True)
        self.assertRedirects(response, reverse("admin_mfa_settings"), fetch_redirect_response=False)
        policy = RoleMFAPolicy.objects.get(role=User.Role.STUDENT)
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.email_enabled)
        self.assertEqual(policy.updated_by, self.admin)
        event = PortalAuditEvent.objects.get(action="mfa_policy_updated")
        self.assertEqual(event.target_name, "Student")
        self.assertIn("Email OTP", event.description)

    def test_policy_change_expires_pending_sign_in_codes_but_preserves_password_reset_codes(self):
        now = timezone.now()
        sign_in = EmailOTPChallenge.objects.create(
            user=self.student,
            purpose=EmailOTPChallenge.Purpose.SIGN_IN,
            code_hash="hashed-sign-in-code",
            sent_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        step_up = EmailOTPChallenge.objects.create(
            user=self.student,
            purpose=EmailOTPChallenge.Purpose.EMAIL_STEP_UP,
            code_hash="hashed-step-up-code",
            sent_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        reset = EmailOTPChallenge.objects.create(
            user=self.student,
            purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
            code_hash="hashed-reset-code",
            sent_at=now,
            expires_at=now + timedelta(minutes=1),
        )

        response = self._all_roles_post(student_enabled=True)

        self.assertRedirects(response, reverse("admin_mfa_settings"), fetch_redirect_response=False)
        sign_in.refresh_from_db()
        step_up.refresh_from_db()
        reset.refresh_from_db()
        self.assertFalse(sign_in.code_hash)
        self.assertFalse(step_up.code_hash)
        self.assertLessEqual(sign_in.expires_at, timezone.now())
        self.assertLessEqual(step_up.expires_at, timezone.now())
        self.assertEqual(reset.code_hash, "hashed-reset-code")
        self.assertGreater(reset.expires_at, timezone.now())

    def test_role_policy_enforces_email_otp_even_when_legacy_global_default_is_off(self):
        RoleMFAPolicy.objects.create(
            role=User.Role.STUDENT,
            enabled=True,
            email_enabled=True,
        )
        self.assertTrue(policy_for_user(self.student)["enabled"])
        with patch("accounts.views._start_otp") as start_otp:
            response = Client().post(reverse("login"), {
                "username": self.student.email,
                "password": "FictionalStudent!2468",
                "otp_channel": "email",
            })
        self.assertRedirects(response, reverse("otp_verify"), fetch_redirect_response=False)
        start_otp.assert_called_once()
        self.assertEqual(start_otp.call_args.args[2], "email")

    @override_settings(AUTHSHIELD_OTP_EXEMPT_EMAILS=frozenset({"mfa-admin@example.test"}))
    def test_admin_mfa_is_mandatory_even_when_saved_policy_is_off_and_email_is_exempt(self):
        RoleMFAPolicy.objects.create(
            role=User.Role.ADMIN,
            enabled=False,
            sms_enabled=True,
            email_enabled=False,
            require_both_factors=True,
        )
        policy = policy_for_user(self.admin)
        self.assertTrue(policy["enabled"])
        self.assertTrue(policy["email"])
        self.assertFalse(policy["sms"])
        self.assertFalse(policy["require_both"])

        with patch("accounts.views._start_otp") as start_otp:
            auth_client = Client()
            response = auth_client.post(reverse("login"), {
                "username": self.admin.email,
                "password": "FictionalAdmin!2468",
            })

        self.assertRedirects(response, reverse("otp_verify"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", auth_client.session)
        start_otp.assert_called_once()
        self.assertEqual(start_otp.call_args.args[2], "email")

    def test_admin_cannot_disable_mfa_from_admin_settings_form(self):
        response = self._all_roles_post()

        self.assertRedirects(response, reverse("admin_mfa_settings"), fetch_redirect_response=False)
        policy = RoleMFAPolicy.objects.get(role=User.Role.ADMIN)
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.email_enabled)

    def test_pre_mfa_admin_session_is_invalidated(self):
        legacy_client = Client()
        session = legacy_client.session
        session[SESSION_KEY] = str(self.admin.pk)
        session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        session[HASH_SESSION_KEY] = AbstractBaseUser._get_session_auth_hash(self.admin)
        session.save()

        response = legacy_client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('dashboard')}",
            fetch_redirect_response=False,
        )
        self.assertNotIn(SESSION_KEY, legacy_client.session)


class KeycloakFlowMFATests(TestCase):
    @patch("accounts.keycloak.keycloak_admin_request")
    def test_only_existing_unconditional_otp_execution_is_changed(self, admin_request):
        admin_request.side_effect = [
            type("Response", (), {"json": lambda self: {"browserFlow": "browser"}})(),
            type("Response", (), {"json": lambda self: [{
                "id": "otp-execution", "providerId": "auth-otp-form", "requirement": "DISABLED",
                "level": 0, "authenticationFlow": False,
            }]})(),
            type("Response", (), {"json": lambda self: None})(),
        ]
        keycloak_set_totp_required(True)
        self.assertEqual(admin_request.call_args.args[:2], ("PUT", "authentication/flows/browser/executions"))
        self.assertEqual(admin_request.call_args.kwargs["payload"]["requirement"], "REQUIRED")

    @patch("accounts.keycloak.keycloak_admin_request")
    def test_conditional_subflow_otp_is_refused(self, admin_request):
        admin_request.side_effect = [
            type("Response", (), {"json": lambda self: {"browserFlow": "browser"}})(),
            type("Response", (), {"json": lambda self: [{
                "id": "otp-execution", "providerId": "auth-otp-form", "requirement": "CONDITIONAL",
                "level": 1, "authenticationFlow": False,
            }]})(),
        ]
        with self.assertRaises(KeycloakAdminError):
            keycloak_set_totp_required(True)
        self.assertEqual(admin_request.call_count, 2)
