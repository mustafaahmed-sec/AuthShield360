from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import User

from .forms import TeacherAssignmentForm, TeacherExamResultForm
from .models import Assignment, Course, Enrollment, ExamResult, StudentRecord


def home(request):
    # Counts from PostgreSQL make the first database-backed slice visible.
    context = {
        "student_count": StudentRecord.objects.count(),
        "course_count": Course.objects.count(),
        "assignment_count": Assignment.objects.count(),
    }
    return render(request, "school/home.html", context)


@login_required
def dashboard(request):
    user = request.user
    if user.role == User.Role.STUDENT:
        context = {
            "record": StudentRecord.objects.filter(student=user).first(),
            "courses": Course.objects.filter(enrollments__student=user).select_related("teacher").order_by("code"),
            "assignments": Assignment.objects.filter(course__enrollments__student=user).select_related("course").order_by("due_date", "id"),
            "results": ExamResult.objects.filter(student=user).select_related("course").order_by("course__code", "exam_name"),
        }
        return render(request, "school/student_dashboard.html", context)
    if user.role == User.Role.TEACHER:
        context = {
            "courses": Course.objects.filter(teacher=user).order_by("code"),
            "assignments": Assignment.objects.filter(course__teacher=user).select_related("course").order_by("due_date", "id"),
            "enrollments": Enrollment.objects.filter(course__teacher=user).select_related("student", "student__student_record", "course").order_by("course__code", "student__full_name"),
            "results": ExamResult.objects.filter(course__teacher=user).select_related("student", "course").order_by("course__code", "student__full_name"),
        }
        return render(request, "school/teacher_dashboard.html", context)
    if user.role == User.Role.ADMIN and user.is_staff and user.is_superuser:
        context = {
            "student_count": StudentRecord.objects.count(),
            "teacher_count": User.objects.filter(role=User.Role.TEACHER).count(),
            "admin_count": User.objects.filter(role=User.Role.ADMIN).count(),
            "course_count": Course.objects.count(),
            "assignment_count": Assignment.objects.count(),
        }
        return render(request, "school/admin_dashboard.html", context)
    raise PermissionDenied("This account has no portal role access.")


def _require_teacher(user):
    if user.role != User.Role.TEACHER or not user.is_active:
        raise PermissionDenied("Only teachers can perform this action.")


@login_required
@require_http_methods(["GET", "POST"])
def create_assignment(request):
    _require_teacher(request.user)
    form = TeacherAssignmentForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Assignment saved for your course.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Create assignment", "submit_label": "Save assignment"})


@login_required
@require_http_methods(["GET", "POST"])
def create_exam_result(request):
    _require_teacher(request.user)
    form = TeacherExamResultForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Exam result saved for an enrolled student.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Record exam result", "submit_label": "Save result"})
