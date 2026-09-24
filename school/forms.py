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
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
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
        grades = ["Kindergarten", *(f"Grade {grade}" for grade in range(1, 13))]
        if student.student_record.grade not in grades:
            grades.append(student.student_record.grade)
        self.fields["grade"].widget = forms.Select(
            choices=[("", "Select grade"), *((grade, grade) for grade in grades)]
        )


class EnrollmentChangeRequestForm(forms.ModelForm):
    student_email = forms.EmailField(
        label="Student email",
        help_text="Enter the fictional school email of the student to add or remove.",
    )

    class Meta:
        model = EnrollmentChangeRequest
        fields = ("course", "action", "student_email", "reason")
        widgets = {"reason": forms.Textarea(attrs={"rows": 3, "maxlength": 500})}

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        courses = Course.objects.filter(teacher=teacher, teacher__is_active=True).order_by("code")
        self.fields["course"].queryset = courses

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        email = cleaned.get("student_email", "").strip().lower()
        action = cleaned.get("action")
        student = User.objects.filter(
            email__iexact=email,
            role=User.Role.STUDENT,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
            student_record__isnull=False,
        ).first() if email else None
        if email and not student:
            self.add_error("student_email", "Enter an active Student account's email address.")
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
        cleaned["student"] = student
        return cleaned
