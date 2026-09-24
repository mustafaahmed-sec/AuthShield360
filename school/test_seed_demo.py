from io import StringIO
from datetime import date, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import User
from school.management.commands.seed_demo import ADMIN_TARGET
from school.models import Assignment, Course, Enrollment, EnrollmentChangeRequest, ExamResult, StudentRecord


class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_pending_signup_does_not_change_demo_target_or_reset(self):
        applicant = User.objects.create_user(
            "demo.student.external@example.test",
            "FictionalDemo!2468",
            full_name="New Applicant",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
            is_active=False,
        )
        output = StringIO()

        call_command("seed_demo", stdout=output)
        self.assertIn("486 seeded students", output.getvalue())
        self.assertEqual(User.objects.filter(role=User.Role.STUDENT).count(), 487)

        call_command("seed_demo", reset=True, stdout=StringIO())
        applicant.refresh_from_db()
        self.assertEqual(applicant.approval_status, User.ApprovalStatus.PENDING)
        self.assertEqual(User.objects.filter(role=User.Role.STUDENT).count(), 487)

    def test_seeded_administrator_roster_matches_its_target(self):
        self.assertEqual(User.objects.filter(role=User.Role.ADMIN).count(), ADMIN_TARGET)

    def test_seed_fails_if_configured_administrator_count_drifts(self):
        with patch("school.management.commands.seed_demo.ADMIN_TARGET", ADMIN_TARGET + 1):
            with self.assertRaisesRegex(CommandError, "administrator roster"):
                call_command("seed_demo", stdout=StringIO())

    def test_reset_schedules_assignments_one_week_ahead(self):
        reset_date = date(2026, 9, 25)
        with patch("school.management.commands.seed_demo.timezone.localdate", return_value=reset_date):
            call_command("seed_demo", reset=True, stdout=StringIO())

        assignment = Assignment.objects.filter(course__code="SCI-101").first()
        self.assertEqual(assignment.due_date, reset_date + timedelta(days=7))

    def test_rerun_preserves_admin_changes_to_existing_demo_records(self):
        replacement = User.objects.create_user(
            "replacement.teacher@example.test",
            "FictionalDemo!2468",
            full_name="Replacement Teacher",
            role=User.Role.TEACHER,
        )
        course = Course.objects.get(code="SCI-101")
        course.teacher = replacement
        course.save(update_fields=["teacher"])
        student = User.objects.get(email="ali.student@example.test")
        record = StudentRecord.objects.get(student=student)
        record.grade = "Grade 11"
        record.save(update_fields=["grade"])
        assignment = Assignment.objects.filter(course=course).first()
        assignment.description = "Administrator edited this sample assignment."
        assignment.save(update_fields=["description"])
        result = ExamResult.objects.filter(course=course, student=student).first()
        result.score = 77
        result.save(update_fields=["score"])
        Enrollment.objects.filter(course=course, student=student).delete()

        call_command("seed_demo", stdout=StringIO())

        course.refresh_from_db()
        record.refresh_from_db()
        assignment.refresh_from_db()
        result.refresh_from_db()
        self.assertEqual(course.teacher, replacement)
        self.assertEqual(record.grade, "Grade 11")
        self.assertEqual(assignment.description, "Administrator edited this sample assignment.")
        self.assertEqual(result.score, 77)
        self.assertFalse(Enrollment.objects.filter(course=course, student=student).exists())

    def test_reset_preserves_course_referenced_by_roster_history(self):
        course = Course.objects.filter(code__startswith="D26-").first()
        teacher = course.teacher
        student = User.objects.get(email="ali.student@example.test")
        change = EnrollmentChangeRequest.objects.create(
            requester=teacher,
            requester_name=teacher.full_name,
            student=student,
            student_name=student.full_name,
            student_email=student.email,
            course=course,
            action=EnrollmentChangeRequest.Action.ADD,
            reason="A fictional roster request for reset coverage.",
        )

        call_command("seed_demo", reset=True, stdout=StringIO())

        change.refresh_from_db()
        self.assertEqual(change.course_id, course.pk)
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())
