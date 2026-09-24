"""Public home and role-specific dashboards."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.models import User

from .audit import record_role_denial
from .models import Assignment, Course, Enrollment, EnrollmentChangeRequest, ExamResult, PortalAuditEvent, StudentRecord


def home(request):
    context = {
        "student_count": StudentRecord.objects.count(),
        "course_count": Course.objects.count(),
        "assignment_count": Assignment.objects.count(),
    }
    return render(request, "school/home.html", context)


@login_required
def dashboard(request):
    user = request.user
    if user.is_portal_student:
        context = {
            "record": StudentRecord.objects.filter(student=user).first(),
            "courses": Course.objects.filter(enrollments__student=user).select_related("teacher").order_by("code"),
            "assignments": Assignment.objects.filter(course__enrollments__student=user)
            .select_related("course").order_by("due_date", "id"),
            "results": ExamResult.objects.filter(student=user).select_related("course").order_by("course__code", "exam_name"),
        }
        return render(request, "school/student_dashboard.html", context)
    if user.is_portal_teacher:
        context = {
            "courses": Course.objects.filter(teacher=user).order_by("code"),
            "assignments": Paginator(
                Assignment.objects.filter(course__teacher=user).select_related("course").order_by("due_date", "id"), 20
            ).get_page(request.GET.get("assignments_page")),
            "enrollments": Paginator(
                Enrollment.objects.filter(course__teacher=user)
                .select_related("student", "student__student_record", "course")
                .order_by("course__code", "student__full_name", "pk"), 20,
            ).get_page(request.GET.get("students_page")),
            "results": Paginator(
                ExamResult.objects.filter(course__teacher=user).select_related("student", "course")
                .order_by("course__code", "student__full_name", "pk"), 20,
            ).get_page(request.GET.get("results_page")),
            "student_count": User.objects.filter(
                role=User.Role.STUDENT, enrollments__course__teacher=user
            ).distinct().count(),
            "recent_changes": PortalAuditEvent.objects.filter(actor=user).order_by("-created_at")[:6],
        }
        return render(request, "school/teacher_dashboard.html", context)
    if user.is_portal_admin:
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
    record_role_denial(user, "role dashboard")
    raise PermissionDenied("This account has no portal role access.")
