from django.test import TestCase
from django.urls import reverse

from .models import User
from school.models import PortalAuditEvent


class AuthenticationAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "student@example.test",
            "FictionalDemo!2468",
            full_name="Test Student",
            role=User.Role.STUDENT,
        )

    def test_successful_login_is_audit_logged(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email,
            "password": "FictionalDemo!2468",
        })

        self.assertEqual(response.status_code, 302)
        event = PortalAuditEvent.objects.get(action="login_success")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_role, User.Role.STUDENT)

    def test_failed_login_is_logged_without_recording_password(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email,
            "password": "incorrect-password",
        })

        self.assertEqual(response.status_code, 200)
        event = PortalAuditEvent.objects.get(action="login_failure")
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_email, self.user.email)
        self.assertNotIn("incorrect-password", event.description)
