from django.test import TestCase
from django.urls import reverse

from .models import User


class RequiredPasswordChangeTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "temporary.teacher@example.test",
            "Temporary!Password2468",
            full_name="Temporary Teacher",
            role=User.Role.TEACHER,
            must_change_password=True,
        )
        self.client.force_login(self.teacher)

    def test_temporary_password_session_cannot_open_dashboard_or_teacher_pages(self):
        for url in (reverse("dashboard"), reverse("teacher_students")):
            response = self.client.get(url)

            self.assertRedirects(
                response,
                reverse("password_change"),
                fetch_redirect_response=False,
            )

    def test_password_change_is_allowed_and_unlocks_portal_access(self):
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("password_change"), {
            "new_password1": "NewPortal!Password3579",
            "new_password2": "NewPortal!Password3579",
        })

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(self.teacher.check_password("NewPortal!Password3579"))
        self.assertEqual(self.client.get(reverse("teacher_students")).status_code, 200)

    def test_user_can_sign_out_without_completing_the_password_change(self):
        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
