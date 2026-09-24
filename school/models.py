from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class StudentRecord(models.Model):
    class Gender(models.TextChoices):
        BOY = "boy", "Boy"
        GIRL = "girl", "Girl"
        NOT_SPECIFIED = "not_specified", "Not specified"

    student = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_record")
    admission_number = models.CharField(max_length=24, unique=True)
    grade = models.CharField(max_length=32)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=16, choices=Gender.choices, blank=True, default="")

    def clean(self):
        if self.student_id and self.student.role != "student":
            raise ValidationError({"student": "Student records require a Student account."})

    def __str__(self):
        return f"{self.admission_number} - {self.student.full_name}"


class Course(models.Model):
    code = models.CharField(max_length=16, unique=True)
    title = models.CharField(max_length=120)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="taught_courses",
    )

    def clean(self):
        if self.teacher_id and self.teacher.role != "teacher":
            raise ValidationError({"teacher": "Courses require a Teacher account."})

    def __str__(self):
        return f"{self.code} - {self.title}"


class PortalAuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="portal_audit_events",
    )
    actor_name = models.CharField(max_length=150)
    actor_email = models.EmailField()
    actor_role = models.CharField(max_length=16)
    action = models.CharField(max_length=48)
    target_name = models.CharField(max_length=150, blank=True)
    description = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email}: {self.action}"


class EnrollmentChangeRequest(models.Model):
    class Action(models.TextChoices):
        ADD = "add", "Request enrollment"
        REMOVE = "remove", "Request removal from class"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="enrollment_change_requests",
    )
    requester_name = models.CharField(max_length=150)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="enrollment_change_requests_for_student",
    )
    student_name = models.CharField(max_length=150)
    student_email = models.EmailField()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollment_change_requests")
    action = models.CharField(max_length=8, choices=Action.choices)
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_enrollment_change_requests",
    )
    review_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("student", "course", "action"),
                condition=Q(status="pending"),
                name="unique_pending_enrollment_change",
            )
        ]

    def __str__(self):
        return f"{self.get_action_display()}: {self.student_name} / {self.course}"


class Enrollment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "course"], name="unique_student_course")]

    def clean(self):
        if self.student_id and self.student.role != "student":
            raise ValidationError({"student": "Enrollments require a Student account."})

    def __str__(self):
        return f"{self.student.full_name} in {self.course.code}"


class Assignment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignments")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    due_date = models.DateField()

    def __str__(self):
        return f"{self.course.code}: {self.title}"


class ExamResult(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_results")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="exam_results")
    exam_name = models.CharField(max_length=120)
    score = models.PositiveSmallIntegerField()
    max_score = models.PositiveSmallIntegerField(default=100)

    def clean(self):
        errors = {}
        if self.student_id and self.student.role != "student":
            errors["student"] = "Exam results require a Student account."
        if self.student_id and self.course_id and not Enrollment.objects.filter(student_id=self.student_id, course_id=self.course_id).exists():
            errors["course"] = "The student must be enrolled in this course."
        if self.max_score is not None and self.max_score <= 0:
            errors["max_score"] = "Maximum score must be greater than zero."
        elif self.max_score is not None and self.score > self.max_score:
            errors["score"] = "Score cannot exceed maximum score."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.student.full_name}: {self.exam_name}"
