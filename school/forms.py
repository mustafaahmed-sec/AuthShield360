"""Teacher forms whose choices are limited to the signed-in teacher's classes."""

from django import forms
from django.core.exceptions import ValidationError

from accounts.models import User

from .models import Assignment, Course, Enrollment, EnrollmentChangeRequest, ExamResult, StudentRecord


class TeacherAssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ("course", "title", "description", "due_date")
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
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


class TeacherStudentNameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("full_name",)
        widgets = {"full_name": forms.TextInput(attrs={"autocomplete": "name"})}


class TeacherStudentRecordForm(forms.ModelForm):
    class Meta:
        model = StudentRecord
        fields = ("grade", "age", "gender")

    def __init__(self, *args, teacher, student, **kwargs):
        super().__init__(*args, **kwargs)
        grades = (
            StudentRecord.objects.filter(student__enrollments__course__teacher=teacher)
            .values_list("grade", flat=True)
            .distinct()
            .order_by("grade")
        )
        self.fields["grade"].widget = forms.Select(
            choices=[("", "Select grade")] + [(grade, grade) for grade in grades]
            + ([(student.student_record.grade, student.student_record.grade)] if student.student_record.grade not in grades else [])
        )


class EnrollmentChangeRequestForm(forms.ModelForm):
    class Meta:
        model = EnrollmentChangeRequest
        fields = ("course", "action", "student", "reason")
        widgets = {"reason": forms.Textarea(attrs={"rows": 3, "maxlength": 500})}

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        courses = Course.objects.filter(teacher=teacher, teacher__is_active=True).order_by("code")
        self.fields["course"].queryset = courses
        course_id = self.data.get("course") or self.initial.get("course")
        action = self.data.get("action") or self.initial.get("action")
        students = User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            student_record__isnull=False,
        )
        if course_id:
            if action == EnrollmentChangeRequest.Action.REMOVE:
                students = students.filter(enrollments__course_id=course_id)
            elif action == EnrollmentChangeRequest.Action.ADD:
                students = students.exclude(enrollments__course_id=course_id)
        else:
            students = students.filter(enrollments__course__in=courses)
        self.fields["student"].queryset = students.distinct().order_by("full_name")

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        student = cleaned.get("student")
        action = cleaned.get("action")
        if course and course.teacher_id != self.teacher.pk:
            raise ValidationError("Choose one of your assigned courses.")
        if course and student and action:
            enrolled = Enrollment.objects.filter(course=course, student=student).exists()
            if action == EnrollmentChangeRequest.Action.ADD and enrolled:
                raise ValidationError("This student is already enrolled in that course.")
            if action == EnrollmentChangeRequest.Action.REMOVE and not enrolled:
                raise ValidationError("This student is not enrolled in that course.")
            if EnrollmentChangeRequest.objects.filter(
                course=course,
                student=student,
                action=action,
                status=EnrollmentChangeRequest.Status.PENDING,
            ).exists():
                raise ValidationError("A matching request is already waiting for administrator review.")
        return cleaned
