"""Teacher forms whose choices are limited to the signed-in teacher's classes."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from accounts.models import User

from .models import Assignment, AttendanceRecord, Course, Enrollment, EnrollmentChangeRequest, ExamResult, StudentRecord


class AdminStudentCreationForm(UserCreationForm):
    phone_number = forms.CharField(
        label="Phone number (optional)",
        required=False,
        max_length=32,
        validators=[RegexValidator(r"^\+?[0-9][0-9\s().-]{6,30}$", "Enter a valid test phone number.")],
    )
    grade = forms.ChoiceField(
        choices=[("", "Choose a grade"), ("Kindergarten", "Kindergarten"), *((f"Grade {grade}", f"Grade {grade}") for grade in range(1, 13))],
    )
    age = forms.IntegerField(
        label="Age (optional)", required=False, min_value=4, max_value=21,
        help_text="Use fictional student details for this demonstration.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("full_name", "email", "phone_number")
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Student full name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "student@example.test"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].label = "Student name"
        self.fields["email"].label = "Student email"
        self.fields["password1"].widget.attrs.update({
            "autocomplete": "new-password", "minlength": "22", "aria-describedby": "password-policy",
        })
        self.fields["password1"].help_text = (
            "Use at least 22 characters, including lowercase and uppercase letters, a number, and a special character."
        )
        self.fields["password2"].label = "Confirm password"
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password", "minlength": "22"})

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def save(self, *, reviewed_by):
        student = super().save(commit=False)
        student.role = User.Role.STUDENT
        student.is_active = True
        student.is_staff = False
        student.is_superuser = False
        student.approval_status = User.ApprovalStatus.APPROVED
        student.reviewed_by = reviewed_by
        student.reviewed_at = timezone.now()
        student.save()
        return student


class AdminAttendanceFilterForm(forms.Form):
    search = forms.CharField(label="Student or course", required=False, max_length=120)
    course = forms.ModelChoiceField(label="Class", queryset=Course.objects.none(), required=False, empty_label="All classes")
    date = forms.DateField(label="Date", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    status = forms.ChoiceField(
        label="Attendance", required=False,
        choices=[("", "All statuses"), *AttendanceRecord.Status.choices],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.order_by("code")


class AttendanceSelectionForm(forms.Form):
    course = forms.ModelChoiceField(queryset=Course.objects.none(), empty_label=None)
    date = forms.DateField(widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(teacher=teacher).order_by("code")

    def clean_date(self):
        day = self.cleaned_data["date"]
        if day > timezone.localdate():
            raise ValidationError("Attendance cannot be marked for a future date.")
        return day


class AttendanceSheetForm(forms.Form):
    def __init__(self, *args, students, current, **kwargs):
        super().__init__(*args, **kwargs)
        for student in students:
            self.fields[f"status_{student.pk}"] = forms.ChoiceField(
                choices=[("", "Not marked"), *AttendanceRecord.Status.choices],
                required=False,
                initial=current.get(student.pk).status if student.pk in current else "",
            )


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
        self.fields["grade"] = forms.ChoiceField(
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
