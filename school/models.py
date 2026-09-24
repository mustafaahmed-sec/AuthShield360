from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="taught_courses")

    def clean(self):
        if self.teacher_id and self.teacher.role != "teacher":
            raise ValidationError({"teacher": "Courses require a Teacher account."})

    def __str__(self):
        return f"{self.code} - {self.title}"


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
        if self.max_score and self.score > self.max_score:
            errors["score"] = "Score cannot exceed maximum score."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.student.full_name}: {self.exam_name}"
