"""Teacher forms whose choices are limited to the signed-in teacher's classes."""

from django import forms
from django.core.exceptions import ValidationError

from accounts.models import User

from .models import Assignment, Course, Enrollment, ExamResult


class TeacherAssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ("course", "title", "description", "due_date")
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(teacher=teacher).order_by("code")


class TeacherExamResultForm(forms.ModelForm):
    class Meta:
        model = ExamResult
        fields = ("course", "student", "exam_name", "score", "max_score")

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        teacher_courses = Course.objects.filter(teacher=teacher)
        self.fields["course"].queryset = teacher_courses.order_by("code")
        self.fields["student"].queryset = User.objects.filter(
            role=User.Role.STUDENT,
            enrollments__course__in=teacher_courses,
        ).distinct().order_by("full_name")

    def clean(self):
        cleaned_data = super().clean()
        course = cleaned_data.get("course")
        student = cleaned_data.get("student")
        if course and student and not Enrollment.objects.filter(course=course, student=student).exists():
            raise ValidationError("Choose a student enrolled in the selected course.")
        return cleaned_data
