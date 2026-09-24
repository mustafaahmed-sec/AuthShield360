from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User

from .audit import record_event
from .forms import (
    EnrollmentChangeRequestForm,
    TeacherAssignmentForm,
    TeacherExamResultForm,
    TeacherStudentNameForm,
    TeacherStudentRecordForm,
)
from .models import (
    Assignment,
    Course,
    Enrollment,
    EnrollmentChangeRequest,
    ExamResult,
    PortalAuditEvent,
    StudentRecord,
)


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
            "student_count": User.objects.filter(
                role=User.Role.STUDENT, enrollments__course__teacher=user
            ).distinct().count(),
            "recent_changes": PortalAuditEvent.objects.filter(actor=user).order_by("-created_at")[:6],
        }
        return render(request, "school/teacher_dashboard.html", context)
    if user.role == User.Role.ADMIN and user.is_staff and user.is_superuser:
        context = {
            "student_count": StudentRecord.objects.count(),
            "teacher_count": User.objects.filter(role=User.Role.TEACHER).count(),
            "admin_count": User.objects.filter(role=User.Role.ADMIN).count(),
            "course_count": Course.objects.count(),
            "assignment_count": Assignment.objects.count(),
            "pending_account_count": User.objects.filter(
                approval_status=User.ApprovalStatus.PENDING,
                role__in=(User.Role.STUDENT, User.Role.TEACHER),
            ).count(),
            "pending_enrollment_count": EnrollmentChangeRequest.objects.filter(
                status=EnrollmentChangeRequest.Status.PENDING
            ).count(),
        }
        return render(request, "school/admin_dashboard.html", context)
    raise PermissionDenied("This account has no portal role access.")


def _require_teacher(user):
    if (
        user.role != User.Role.TEACHER
        or not user.is_active
        or user.approval_status != User.ApprovalStatus.APPROVED
    ):
        raise PermissionDenied("Only teachers can perform this action.")


@login_required
@require_http_methods(["GET", "POST"])
def create_assignment(request):
    _require_teacher(request.user)
    form = TeacherAssignmentForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        assignment = form.save()
        record_event(
            request.user,
            "assignment_created",
            f"Created assignment {assignment.title} for {assignment.course.code}.",
            target_name=assignment.title,
        )
        messages.success(request, "Assignment saved for your course.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Create assignment", "submit_label": "Save assignment"})


@login_required
@require_http_methods(["GET", "POST"])
def create_exam_result(request):
    _require_teacher(request.user)
    form = TeacherExamResultForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        result = form.save()
        record_event(
            request.user,
            "exam_result_recorded",
            f"Recorded a result for {result.exam_name} in {result.course.code}.",
            target_name=result.student.full_name,
        )
        messages.success(request, "Exam result saved for an enrolled student.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Record exam result", "submit_label": "Save result"})
