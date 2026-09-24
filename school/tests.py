from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .models import Assignment, Course, Enrollment, EnrollmentChangeRequest, ExamResult, PortalAuditEvent, StudentRecord


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
                "password1": "FictionalDemo!2468-Strong",
                "password2": "FictionalDemo!2468-Strong",
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

    def test_pending_accounts_are_paginated(self):
        for number in range(21):
            User.objects.create_user(
                f"applicant{number}@example.test", "FictionalDemo!2468",
                full_name=f"Applicant {number}", role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.PENDING, is_active=False,
            )
        self.client.force_login(self.admin)

        first = self.client.get(reverse("admin_management"))
        second = self.client.get(reverse("admin_management") + "?pending_page=2")

        self.assertEqual(len(first.context["pending_accounts"]), 20)
        self.assertEqual(len(second.context["pending_accounts"]), 1)

    def test_administrator_can_view_but_not_edit_audit_events(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:school_portalauditevent_changelist"))
        self.assertEqual(response.status_code, 200)

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
            "record-grade": "Grade 9",
            "record-age": "13",
            "record-gender": "not_specified",
        })
        self.assertRedirects(response, reverse("teacher_students"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, "Updated Student")
        self.assertEqual(self.student.student_record.grade, "Grade 9")
        event = PortalAuditEvent.objects.get(
            actor=self.teacher,
            action="student_school_record_updated",
            target_name="Updated Student",
        )
        self.assertIn("name, grade, age, gender", event.description)

    def test_teacher_edit_rejects_grade_outside_offered_choices(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("edit_assigned_student", args=[self.student.pk]), {
            "name-full_name": self.student.full_name,
            "record-grade": "Grade 99",
            "record-age": "13",
            "record-gender": "not_specified",
        })
        self.assertEqual(response.status_code, 200)
        self.student.student_record.refresh_from_db()
        self.assertEqual(self.student.student_record.grade, "Grade 8")


    def test_teacher_must_request_roster_change_and_admin_approval_applies_it(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("request_enrollment_change"), {
            "course": self.course.pk,
            "action": EnrollmentChangeRequest.Action.REMOVE,
            "student_email": self.student.email,
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

    def test_teacher_cannot_submit_work_for_another_teachers_course_or_students(self):
        self.client.force_login(self.teacher)
        assignment_response = self.client.post(reverse("create_assignment"), {
            "course": self.other_course.pk,
            "title": "Unauthorized assignment",
            "description": "Test only",
            "due_date": "2026-10-01",
        })
        self.assertEqual(assignment_response.status_code, 200)
        self.assertFalse(Assignment.objects.filter(title="Unauthorized assignment").exists())

        result_response = self.client.post(reverse("create_exam_result"), {
            "course": self.course.pk,
            "student": self.other_student.pk,
            "exam_name": "Unauthorized result",
            "score": 10,
            "max_score": 10,
        })
        self.assertEqual(result_response.status_code, 200)
        self.assertFalse(ExamResult.objects.filter(exam_name="Unauthorized result").exists())

    def test_teacher_can_request_an_existing_student_from_another_class(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("request_enrollment_change"), {
            "course": self.course.pk,
            "action": EnrollmentChangeRequest.Action.ADD,
            "student_email": self.other_student.email,
            "reason": "Student transferred into this section.",
        })

        self.assertRedirects(response, reverse("teacher_students"))
        self.assertTrue(EnrollmentChangeRequest.objects.filter(
            requester=self.teacher,
            student=self.other_student,
            course=self.course,
            action=EnrollmentChangeRequest.Action.ADD,
        ).exists())
        self.assertFalse(Enrollment.objects.filter(student=self.other_student, course=self.course).exists())

    def test_roster_request_with_non_numeric_course_is_rejected_without_error(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("request_enrollment_change"), {
            "course": "not-a-number",
            "action": EnrollmentChangeRequest.Action.ADD,
            "student_email": self.other_student.email,
            "reason": "Invalid course input must not create a request.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EnrollmentChangeRequest.objects.exists())

    def test_teacher_cannot_open_administrator_management(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("admin_management"))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PortalAuditEvent.objects.filter(
            actor=self.teacher,
            action="role_access_denied",
            target_name="administrator management",
        ).exists())

    def test_teacher_dashboard_students_are_paginated(self):
        for number in range(20):
            student = User.objects.create_user(
                f"extra{number}@example.test", "FictionalDemo!2468",
                full_name=f"Extra Student {number}", role=User.Role.STUDENT,
            )
            StudentRecord.objects.create(
                student=student, admission_number=f"EX-{number:04}", grade="Grade 8"
            )
            Enrollment.objects.create(student=student, course=self.course)
        self.client.force_login(self.teacher)

        first = self.client.get(reverse("dashboard"))
        second = self.client.get(reverse("dashboard") + "?students_page=2")

        self.assertEqual(len(first.context["enrollments"]), 20)
        self.assertEqual(len(second.context["enrollments"]), 1)


class StudentRoleBoundaryTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "student-boundary@example.test", "student-password",
            full_name="Boundary Student", role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            "other-student@example.test", "student-password",
            full_name="Other Student", role=User.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            "boundary-teacher@example.test", "teacher-password",
            full_name="Boundary Teacher", role=User.Role.TEACHER,
        )
        self.course = Course.objects.create(code="BND-101", title="Boundary course", teacher=self.teacher)
        StudentRecord.objects.create(student=self.student, admission_number="BND-001", grade="Grade 8")
        StudentRecord.objects.create(student=self.other_student, admission_number="BND-002", grade="Grade 9")
        Enrollment.objects.create(student=self.student, course=self.course)
        Assignment.objects.create(course=self.course, title="Visible assignment", due_date="2026-10-01")

    def test_student_dashboard_only_shows_own_scope(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible assignment")
        self.assertNotContains(response, "Other Student")
        self.assertEqual(response.context["record"].student, self.student)

    def test_student_is_denied_direct_teacher_and_administrator_urls(self):
        self.client.force_login(self.student)
        protected_paths = (
            "teacher_students",
            "create_assignment",
            "create_exam_result",
            "request_enrollment_change",
            "admin_management",
        )

        for path_name in protected_paths:
            with self.subTest(path=path_name):
                response = self.client.get(reverse(path_name))
                self.assertEqual(response.status_code, 403)

        self.assertGreaterEqual(
            PortalAuditEvent.objects.filter(actor=self.student, action="role_access_denied").count(),
            3,
        )


class StudentDashboardProgressTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "progress-student@example.test", "student-password",
            full_name="Progress Student", role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            "other-progress-student@example.test", "student-password",
            full_name="Other Progress Student", role=User.Role.STUDENT,
        )
        self.teacher = User.objects.create_user(
            "progress-teacher@example.test", "teacher-password",
            full_name="Progress Teacher", role=User.Role.TEACHER,
        )
        self.course = Course.objects.create(
            code="PROG-101", title="Progress course", teacher=self.teacher,
        )
        self.ungraded_course = Course.objects.create(
            code="PROG-201", title="Ungraded course", teacher=self.teacher,
        )
        self.other_course = Course.objects.create(
            code="PROG-301", title="Other course", teacher=self.teacher,
        )
        Enrollment.objects.create(student=self.student, course=self.course)
        Enrollment.objects.create(student=self.student, course=self.ungraded_course)
        Enrollment.objects.create(student=self.other_student, course=self.course)
        Enrollment.objects.create(student=self.other_student, course=self.other_course)
        ExamResult.objects.create(
            student=self.student, course=self.course, exam_name="First result", score=80, max_score=100,
        )
        ExamResult.objects.create(
            student=self.student, course=self.course, exam_name="Second result", score=18, max_score=20,
        )
        ExamResult.objects.create(
            student=self.other_student, course=self.course, exam_name="Other student's result", score=20, max_score=100,
        )

    def test_dashboard_averages_only_this_students_results_and_shows_ungraded_courses(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("dashboard"))

        averages = {course.code: course.average_percent for course in response.context["courses"]}
        self.assertAlmostEqual(averages["PROG-101"], 85.0)
        self.assertIsNone(averages["PROG-201"])
        self.assertNotIn("PROG-301", averages)
        self.assertContains(response, "Average result: 85.0%")
        self.assertContains(response, "No graded results yet.")

    def test_due_soon_includes_today_through_day_fourteen_only(self):
        today = date(2026, 9, 25)
        for title, due_date in (
            ("Due today", today),
            ("Due in fourteen days", today + timedelta(days=14)),
            ("Due in fifteen days", today + timedelta(days=15)),
            ("Past assignment", today - timedelta(days=1)),
        ):
            Assignment.objects.create(course=self.course, title=title, due_date=due_date)
        Assignment.objects.create(
            course=self.other_course, title="Not enrolled", due_date=today + timedelta(days=3),
        )
        self.client.force_login(self.student)

        with patch("school.views.timezone.localdate", return_value=today):
            response = self.client.get(reverse("dashboard"))

        titles = list(response.context["due_soon"].values_list("title", flat=True))
        self.assertEqual(titles, ["Due today", "Due in fourteen days"])
        self.assertContains(response, "Due soon")


class DjangoAdminRoleBoundaryTests(TestCase):
    def test_staff_flagged_teacher_cannot_access_django_admin(self):
        teacher = User.objects.create_user(
            "staff-teacher@example.test",
            "teacher-password",
            full_name="Staff Flagged Teacher",
            role=User.Role.TEACHER,
            is_staff=True,
        )
        self.client.force_login(teacher)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(PortalAuditEvent.objects.filter(
            actor=teacher,
            action="role_access_denied",
            target_name="Django administrator",
        ).exists())

    @override_settings(AUTHSHIELD_BASELINE_LOGIN_ENABLED=False)
    def test_django_admin_login_obeys_baseline_login_gate(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 403)

    def test_django_admin_login_uses_portal_login(self):
        response = self.client.get(reverse("admin:login"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)


class PortalNavigationAndFeedbackTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin@example.test", "admin-password", full_name="Portal Administrator",
        )
        self.teacher = User.objects.create_user(
            "teacher@example.test", "teacher-password", full_name="Portal Teacher", role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            "student@example.test", "student-password", full_name="Portal Student", role=User.Role.STUDENT,
        )

    def test_guest_navigation_has_specific_request_and_sign_in_links(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sign in")
        self.assertContains(response, "Enroll as student")
        self.assertContains(response, "Join as teacher")
        self.assertContains(response, "Check request status")
        self.assertNotContains(response, "Security log")
        self.assertNotContains(response, "Accounts &amp; requests")

    def test_role_navigation_only_shows_each_users_relevant_destinations(self):
        cases = (
            (self.admin, ("Accounts &amp; requests", "Security log"), ("My students",)),
            (self.teacher, ("My students",), ("Security log", "Accounts &amp; requests")),
            (self.student, (), ("Security log", "Accounts &amp; requests", "My students")),
        )
        for user, expected, absent in cases:
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.status_code, 200)
                for label in expected:
                    self.assertContains(response, label)
                for label in absent:
                    self.assertNotContains(response, label)

    def test_identity_chip_shows_name_and_role_without_email(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Portal Teacher · Teacher")
        self.assertNotContains(response, self.teacher.email)

    @override_settings(DEBUG=True, AUTHSHIELD_PROTECTED_DEMO=False)
    def test_authentication_mode_badge_only_appears_in_local_or_protected_demo(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Password-only baseline")
        with override_settings(DEBUG=False, AUTHSHIELD_PROTECTED_DEMO=True):
            response = self.client.get(reverse("home"))
        self.assertContains(response, "Password-only baseline")
        with override_settings(DEBUG=False, AUTHSHIELD_PROTECTED_DEMO=False):
            response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Password-only baseline")

    def test_messages_have_distinct_label_and_accessibility_role(self):
        self.client.force_login(self.admin)
        applicant = User.objects.create_user(
            "pending@example.test", "pending-password", full_name="Pending Applicant",
            role=User.Role.STUDENT, approval_status=User.ApprovalStatus.PENDING, is_active=False,
        )
        error = self.client.post(
            reverse("review_account_request", args=[applicant.pk]), {"action": "bad"}, follow=True
        )
        self.assertRedirects(error, reverse("admin_management"))
        self.assertContains(error, "message-error")
        self.assertContains(error, "Error:")
        self.assertContains(error, 'role="alert"')

        teacher_request = User.objects.create_user(
            "teacher-request@example.test", "teacher-password", full_name="Teacher Request",
            role=User.Role.TEACHER, approval_status=User.ApprovalStatus.PENDING, is_active=False,
        )
        success = self.client.post(
            reverse("review_account_request", args=[teacher_request.pk]), {"action": "approve"}, follow=True
        )
        self.assertRedirects(success, reverse("admin_management"))
        self.assertContains(success, "message-success")
        self.assertContains(success, "Success:")
        self.assertContains(success, 'role="status"')

    def test_logout_confirms_session_ended_and_login_next_explains_required_sign_in(self):
        self.client.force_login(self.student)
        logout = self.client.post(reverse("logout"), follow=True)
        self.assertContains(logout, "You have signed out. This session can no longer be used.")
        login = self.client.get(reverse("login") + "?next=/dashboard/")
        self.assertContains(login, "Please sign in to continue. Your previous session is not active.")

    @override_settings(DEBUG=False)
    def test_forbidden_and_missing_pages_use_custom_templates(self):
        self.client.force_login(self.teacher)
        forbidden = self.client.get(reverse("admin_management"))
        self.assertEqual(forbidden.status_code, 403)
        self.assertContains(
            forbidden,
            "You don't have permission to open this page. This attempt has been recorded.",
            status_code=403,
        )
        missing = self.client.get("/definitely-not-a-portal-page/")
        self.assertEqual(missing.status_code, 404)
        self.assertContains(missing, "The address may be incorrect", status_code=404)

    def test_auth_forms_expose_submission_feedback_for_progressive_enhancement(self):
        self.assertContains(self.client.get(reverse("login")), 'data-busy-label="Signing in…"')
        self.assertContains(self.client.get(reverse("student_signup")), 'data-busy-label="Submitting request…"')
        self.assertContains(self.client.get(reverse("registration_status")), 'data-busy-label="Checking status…"')
