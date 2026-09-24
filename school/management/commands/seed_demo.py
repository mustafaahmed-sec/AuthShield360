"""Create only the named fictional records used in the local demonstration."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from school.models import Assignment, Course, Enrollment, ExamResult, StudentRecord


TEACHER_EMAIL = "mina.teacher@example.test"
STUDENT_EMAIL = "ali.student@example.test"
COURSE_CODE = "SCI-101"


class Command(BaseCommand):
    help = "Create repeatable fictional school data; --reset restores this command's named sample records."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Restore only the named demo records and disable their passwords")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["reset"]:
            Assignment.objects.filter(course__code=COURSE_CODE, title="Observation journal").delete()
            ExamResult.objects.filter(student__email=STUDENT_EMAIL, course__code=COURSE_CODE, exam_name="Sample term exam").delete()
            Enrollment.objects.filter(student__email=STUDENT_EMAIL, course__code=COURSE_CODE).delete()
            StudentRecord.objects.filter(student__email=STUDENT_EMAIL, admission_number="AS-0001").delete()

        teacher, teacher_created = User.objects.get_or_create(
            email=TEACHER_EMAIL,
            defaults={"full_name": "Mina Rahman", "role": User.Role.TEACHER},
        )
        student, student_created = User.objects.get_or_create(
            email=STUDENT_EMAIL,
            defaults={"full_name": "Ali Khan", "role": User.Role.STUDENT},
        )
        for user, created, name, role in (
            (teacher, teacher_created, "Mina Rahman", User.Role.TEACHER),
            (student, student_created, "Ali Khan", User.Role.STUDENT),
        ):
            if created or options["reset"]:
                user.full_name = name
                user.role = role
                user.set_unusable_password()
                user.save(update_fields=["full_name", "role", "password"])

        StudentRecord.objects.update_or_create(
            student=student,
            defaults={"admission_number": "AS-0001", "grade": "Grade 10"},
        )
        course, _ = Course.objects.update_or_create(
            code=COURSE_CODE,
            defaults={"title": "Foundations of Science", "teacher": teacher},
        )
        Enrollment.objects.get_or_create(student=student, course=course)
        Assignment.objects.update_or_create(
            course=course,
            title="Observation journal",
            defaults={
                "description": "Record three observations from a fictional lab exercise.",
                "due_date": timezone.localdate() + timedelta(days=7),
            },
        )
        ExamResult.objects.update_or_create(
            student=student,
            course=course,
            exam_name="Sample term exam",
            defaults={"score": 84, "max_score": 100},
        )
        self.stdout.write(self.style.SUCCESS("Fictional school records are ready. No account passwords were displayed."))
