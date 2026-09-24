from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .models import Course, Enrollment, EnrollmentChangeRequest, StudentRecord


class AccountApprovalFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="reviewer@example.test", password="test-admin-password",
            full_name="Test Reviewer",
        )

    def test_student_and_teacher_signups_wait_for_admin_approval(self):
        for role, path in (("student", "student_signup"), ("teacher", "teacher_signup")):
            response = self.client.post(reverse(path), {
                "full_name": f"Test {role.title()}",
                "email": f"{role}@example.test",
                "phone_number": "+1 555 010 0100",
                "password1": "FictionalDemo!2468",
                "password2": "FictionalDemo!2468",
            })
            self.assertRedirects(response, reverse("registration_status"))
            user = User.objects.get(email=f"{role}@example.test")
            self.assertEqual(user.role, role)
            self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)
            self.assertFalse(user.is_active)

    def test_administrator_management_screen_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accounts and requests")
        self.assertContains(response, "New account requests")

    @override_settings(AUTHSHIELD_BASELINE_LOGIN_ENABLED=True)
    def test_pending_account_cannot_sign_in_and_admin_approval_enables_it(self):
        student = User.objects.create_user(
            "pending@example.test", "FictionalDemo!2468", full_name="Pending Student",
            role=User.Role.STUDENT, approval_status=User.ApprovalStatus.PENDING,
            is_active=False,
        )
        response = self.client.post(reverse("login"), {
            "username": student.email, "password": "FictionalDemo!2468",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        self.client.force_login(self.admin)
        response = self.client.post(reverse("review_account_request", args=[student.pk]), {"action": "approve"})
        self.assertRedirects(response, reverse("admin_management"))
        student.refresh_from_db()
        self.assertTrue(student.is_active)
        self.assertEqual(student.approval_status, User.ApprovalStatus.APPROVED)
        self.assertTrue(StudentRecord.objects.filter(student=student, grade="Unassigned").exists())


class TeacherRosterPermissionTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "teacher@example.test", "teacher-password", full_name="Teacher One",
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            "other@example.test", "teacher-password", full_name="Teacher Two",
            role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            "student@example.test", "student-password", full_name="Assigned Student",
            role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            "outside@example.test", "student-password", full_name="Outside Student",
            role=User.Role.STUDENT,
        )
        for n, user in enumerate((self.student, self.other_student), start=1):
            StudentRecord.objects.create(student=user, admission_number=f"TST-{n:04}", grade="Grade 8")
        self.course = Course.objects.create(code="TST-101", title="Test course", teacher=self.teacher)
        self.other_course = Course.objects.create(code="TST-201", title="Other course", teacher=self.other_teacher)
        self.enrollment = Enrollment.objects.create(student=self.student, course=self.course)
        Enrollment.objects.create(student=self.other_student, course=self.other_course)

    def test_teacher_search_only_returns_assigned_roster_and_can_edit_its_record(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("teacher_students"))
        self.assertContains(response, "Assigned Student")
        self.assertNotContains(response, "Outside Student")

        response = self.client.get(reverse("edit_assigned_student", args=[self.other_student.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("edit_assigned_student", args=[self.student.pk]), {
            "name-full_name": "Updated Student",
            "record-grade": "Grade 8",
            "record-age": "13",
            "record-gender": "not_specified",
        })
        self.assertRedirects(response, reverse("teacher_students"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, "Updated Student")

    def test_teacher_must_request_roster_change_and_admin_approval_applies_it(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("request_enrollment_change"), {
            "course": self.course.pk,
            "action": EnrollmentChangeRequest.Action.REMOVE,
            "student": self.student.pk,
            "reason": "Student transferred to another section.",
        })
        self.assertRedirects(response, reverse("teacher_students"))
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists())
        change = EnrollmentChangeRequest.objects.get()

        self.client.force_login(self.other_teacher)
        response = self.client.post(reverse("review_enrollment_request", args=[change.pk]), {"action": "approve"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists())

        admin = User.objects.create_superuser(
            "reviewer@example.test", "admin-password", full_name="Reviewer",
        )
        self.client.force_login(admin)
        response = self.client.post(reverse("review_enrollment_request", args=[change.pk]), {"action": "approve"})
        self.assertRedirects(response, reverse("admin_management"))
        self.assertFalse(Enrollment.objects.filter(pk=self.enrollment.pk).exists())

    def test_teacher_cannot_open_administrator_management(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("admin_management"))
        self.assertEqual(response.status_code, 403)
