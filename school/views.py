"""Public home and role-specific dashboards."""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User

from .audit import record_role_denial
from .models import (
    Announcement,
    Assignment,
    AttendanceRecord,
    Course,
    Enrollment,
    EnrollmentChangeRequest,
    ExamResult,
    PortalAuditEvent,
    StudentRecord,
    TeacherAttendanceRecord,
)


def active_announcements_for(user):
    today = timezone.localdate()
    return Announcement.objects.filter(
        is_active=True,
    ).filter(
        Q(audience=Announcement.Audience.ALL) | Q(audience=user.role),
    ).filter(
        Q(starts_on__isnull=True) | Q(starts_on__lte=today),
    ).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today),
    )


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
        today = timezone.localdate()
        attendance_summary = []
        for item in (
            AttendanceRecord.objects.filter(student=user)
            .values("course__code", "course__title")
            .annotate(
                present=Count("pk", filter=Q(status=AttendanceRecord.Status.PRESENT)),
                absent=Count("pk", filter=Q(status=AttendanceRecord.Status.ABSENT)),
                late=Count("pk", filter=Q(status=AttendanceRecord.Status.LATE)),
                excused=Count("pk", filter=Q(status=AttendanceRecord.Status.EXCUSED)),
            ).order_by("course__code")
        ):
            counted = item["present"] + item["absent"] + item["late"]
            item["attended_percent"] = round(100 * (item["present"] + item["late"]) / counted, 1) if counted else None
            attendance_summary.append(item)
        attendance_days_counted = sum(
            item["present"] + item["absent"] + item["late"] for item in attendance_summary
        )
        attendance_days_attended = sum(
            item["present"] + item["late"] for item in attendance_summary
        )
        overall_attendance_percent = (
            round(100 * attendance_days_attended / attendance_days_counted, 1)
            if attendance_days_counted else None
        )
        result_totals = ExamResult.objects.filter(student=user).aggregate(
            earned=Sum("score"), possible=Sum("max_score")
        )
        grade_average_percent = (
            round(100 * result_totals["earned"] / result_totals["possible"], 1)
            if result_totals["possible"] else None
        )
        courses = (
            Course.objects.filter(enrollments__student=user)
            .select_related("teacher")
            .annotate(
                average_percent=Avg(
                    ExpressionWrapper(
                        F("exam_results__score") * 100.0 / F("exam_results__max_score"),
                        output_field=FloatField(),
                    ),
                    filter=Q(exam_results__student=user),
                )
            )
            .order_by("code")
        )
        due_soon = Assignment.objects.filter(
            course__enrollments__student=user,
            due_date__gte=today,
            due_date__lte=today + timedelta(days=14),
        ).select_related("course").order_by("due_date", "id")
        context = {
            "announcements": active_announcements_for(user),
            "record": StudentRecord.objects.filter(student=user).first(),
            "attendance_summary": attendance_summary,
            "attendance_days_counted": attendance_days_counted,
            "overall_attendance_percent": overall_attendance_percent,
            "recent_attendance": AttendanceRecord.objects.filter(student=user)
            .select_related("course").order_by("-date", "course__code")[:12],
            "courses": courses,
            "due_soon": due_soon,
            "due_soon_count": due_soon.count(),
            "assignments": Assignment.objects.filter(course__enrollments__student=user)
            .select_related("course").order_by("due_date", "id"),
            "results": ExamResult.objects.filter(student=user).select_related("course").order_by("course__code", "exam_name"),
            "recent_results": ExamResult.objects.filter(student=user)
            .select_related("course").order_by("-pk")[:3],
            "grade_average_percent": grade_average_percent,
            "graded_assessment_count": ExamResult.objects.filter(student=user).count(),
        }
        return render(request, "school/student_dashboard.html", context)
    if user.is_portal_teacher:
        context = {
            "announcements": active_announcements_for(user),
            "schoolwide_student_count": StudentRecord.objects.filter(
                student__role=User.Role.STUDENT,
                student__is_active=True,
                student__approval_status=User.ApprovalStatus.APPROVED,
            ).count() if user.can_manage_all_students else None,
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
            "announcements": active_announcements_for(user),
            "attendance_count": AttendanceRecord.objects.count(),
            "teacher_attendance_count": TeacherAttendanceRecord.objects.count(),
            "student_count": StudentRecord.objects.count(),
            "teacher_count": User.objects.filter(
                role=User.Role.TEACHER,
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED,
            ).count(),
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
    record_role_denial(user, "role dashboard", request)
    raise PermissionDenied("This account has no portal role access.")
