from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from school.models import AttendanceRecord, Enrollment

class Command(BaseCommand):
    help = "Add repeatable fictional attendance history for existing course enrollments."

    def handle(self, *args, **options):
        today = timezone.localdate()
        rows = []
        existing = set(AttendanceRecord.objects.values_list("student_id", "course_id", "date"))
        for index, enrollment in enumerate(Enrollment.objects.select_related("course", "course__teacher", "student"), start=1):
            for session in range(10, 0, -1):
                day = today - timedelta(days=session * 7)
                key = (enrollment.student_id, enrollment.course_id, day)
                if key in existing:
                    continue
                pattern = (index * 7 + session) % 20
                status = (
                    AttendanceRecord.Status.ABSENT if pattern in (0, 1)
                    else AttendanceRecord.Status.LATE if pattern in (2, 3)
                    else AttendanceRecord.Status.EXCUSED if pattern == 4
                    else AttendanceRecord.Status.PRESENT
                )
                rows.append(AttendanceRecord(
                    student=enrollment.student, course=enrollment.course, date=day,
                    status=status, marked_by=enrollment.course.teacher,
                ))
        AttendanceRecord.objects.bulk_create(rows, ignore_conflicts=True, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"Added {len(rows)} fictional attendance records."))
