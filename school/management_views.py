"""Administrator account controls and teacher student-management views."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User

from .audit import record_event
from .forms import (
    EnrollmentChangeRequestForm,
    TeacherStudentNameForm,
    TeacherStudentRecordForm,
)
from .models import Course, Enrollment, EnrollmentChangeRequest, PortalAuditEvent, StudentRecord


def _require_admin(user):
    if user.role != User.Role.ADMIN or not user.is_staff or not user.is_superuser or not user.is_active:
        raise PermissionDenied("Only an active Administrator can manage school accounts.")


def _require_teacher(user):
    if user.role != User.Role.TEACHER or not user.is_active or user.approval_status != User.ApprovalStatus.APPROVED:
        raise PermissionDenied("Only an approved, active Teacher can manage assigned students.")


@login_required
def admin_management(request):
    _require_admin(request.user)
    search = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    accounts = User.objects.filter(role__in=(User.Role.STUDENT, User.Role.TEACHER)).order_by("role", "full_name")
    if role in (User.Role.STUDENT, User.Role.TEACHER):
        accounts = accounts.filter(role=role)
    if status == "pending":
        accounts = accounts.filter(approval_status=User.ApprovalStatus.PENDING)
    elif status == "inactive":
        accounts = accounts.filter(is_active=False).exclude(approval_status=User.ApprovalStatus.PENDING)
    elif status == "active":
        accounts = accounts.filter(is_active=True)
    if search:
        accounts = accounts.filter(Q(full_name__icontains=search) | Q(email__icontains=search))
    context = {
        "pending_accounts": User.objects.filter(
            approval_status=User.ApprovalStatus.PENDING,
            role__in=(User.Role.STUDENT, User.Role.TEACHER),
        ).order_by("date_joined"),
        "accounts": Paginator(accounts.select_related("student_record"), 40).get_page(request.GET.get("page")),
        "pending_changes": EnrollmentChangeRequest.objects.filter(
            status=EnrollmentChangeRequest.Status.PENDING
        ).select_related("requester", "student", "course").order_by("created_at"),
        "recent_events": PortalAuditEvent.objects.all()[:20],
        "search": search,
        "role_filter": role,
        "status_filter": status,
        "student_count": User.objects.filter(role=User.Role.STUDENT).count(),
        "teacher_count": User.objects.filter(role=User.Role.TEACHER).count(),
    }
    return render(request, "school/admin_management.html", context)


@login_required
@require_POST
@transaction.atomic
def review_account_request(request, user_id):
    _require_admin(request.user)
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
        approval_status=User.ApprovalStatus.PENDING,
    )
    action = request.POST.get("action")
    if action == "approve":
        account.approval_status = User.ApprovalStatus.APPROVED
        account.is_active = True
        if account.role == User.Role.STUDENT:
            StudentRecord.objects.get_or_create(
                student=account,
                defaults={"admission_number": f"AS-R{account.pk:06d}", "grade": "Unassigned"},
            )
        status_label = "approved"
        summary = "Approved an account request. The account can now sign in."
    elif action == "reject":
        account.approval_status = User.ApprovalStatus.REJECTED
        account.is_active = False
        status_label = "rejected"
        summary = "Rejected an account access request."
    else:
        messages.error(request, "Choose approve or reject.")
        return redirect("admin_management")
    account.reviewed_at = timezone.now()
    account.reviewed_by = request.user
    account.save(update_fields=("approval_status", "is_active", "reviewed_at", "reviewed_by"))
    record_event(request.user, f"account_request_{status_label}", summary, target_name=account.full_name)
    messages.success(request, f"{account.get_role_display()} request for {account.full_name} was {status_label}.")
    return redirect("admin_management")


@login_required
@require_POST
@transaction.atomic
def change_account_access(request, user_id):
    _require_admin(request.user)
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
        approval_status=User.ApprovalStatus.APPROVED,
    )
    action = request.POST.get("action")
    if action == "deactivate":
        account.is_active = False
        status_label = "deactivated"
        summary = "Removed sign-in access while preserving school records."
    elif action == "reactivate":
        account.is_active = True
        status_label = "reactivated"
        summary = "Restored sign-in access."
    else:
        messages.error(request, "Choose deactivate or reactivate.")
        return redirect("admin_management")
    account.save(update_fields=("is_active",))
    record_event(request.user, f"account_{status_label}", summary, target_name=account.full_name)
    messages.success(request, f"Access for {account.full_name} was {status_label}.")
    return redirect("admin_management")


@login_required
@require_POST
@transaction.atomic
def delete_school_account(request, user_id):
    _require_admin(request.user)
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
    )
    label = account.full_name
    email = account.email
    role_label = account.get_role_display().lower()
    record_event(
        request.user,
        "school_account_deleted",
        f"Deleted the {role_label} account {email}; linked academic records follow their configured retention rules.",
        target_name=label,
    )
    account.delete()
    messages.success(request, f"The account for {label} was deleted.")
    return redirect("admin_management")


@login_required
@require_POST
@transaction.atomic
def review_enrollment_request(request, request_id):
    _require_admin(request.user)
    change = get_object_or_404(
        EnrollmentChangeRequest.objects.select_for_update().select_related("student", "course"),
        pk=request_id,
        status=EnrollmentChangeRequest.Status.PENDING,
    )
    action = request.POST.get("action")
    if action not in ("approve", "reject"):
        messages.error(request, "Choose approve or reject.")
        return redirect("admin_management")
    if action == "approve":
        if change.student_id is None or not change.student.is_active:
            messages.error(request, "This student account is no longer active; the request was left unchanged.")
            return redirect("admin_management")
        if change.action == EnrollmentChangeRequest.Action.ADD:
            Enrollment.objects.get_or_create(student=change.student, course=change.course)
        else:
            Enrollment.objects.filter(student=change.student, course=change.course).delete()
        change.status = EnrollmentChangeRequest.Status.APPROVED
        status_label = "approved"
        summary = "Approved the requested class roster change."
    else:
        change.status = EnrollmentChangeRequest.Status.REJECTED
        status_label = "rejected"
        summary = "Rejected the requested class roster change."
    change.reviewed_by = request.user
    change.reviewed_at = timezone.now()
    change.review_note = request.POST.get("review_note", "").strip()[:300]
    change.save(update_fields=("status", "reviewed_by", "reviewed_at", "review_note"))
    record_event(request.user, f"enrollment_request_{status_label}", summary, target_name=change.student_name)
    messages.success(request, summary)
    return redirect("admin_management")


@login_required
def teacher_students(request):
    _require_teacher(request.user)
    teacher_courses = Course.objects.filter(teacher=request.user, teacher__is_active=True)
    roster = User.objects.filter(
        role=User.Role.STUDENT,
        is_active=True,
        enrollments__course__in=teacher_courses,
        student_record__isnull=False,
    ).select_related("student_record").prefetch_related(Prefetch("enrollments", queryset=Enrollment.objects.filter(course__teacher=request.user).select_related("course"))).distinct()
    grades = list(
        StudentRecord.objects.filter(student__in=roster)
        .values_list("grade", flat=True)
        .distinct()
        .order_by("grade")
    )
    students = roster
    search = request.GET.get("q", "").strip()
    grade = request.GET.get("grade", "").strip()
    course_id = request.GET.get("course", "").strip()
    if search:
        students = students.filter(
            Q(full_name__icontains=search)
            | Q(email__icontains=search)
            | Q(student_record__admission_number__icontains=search)
        )
    if grade in grades:
        students = students.filter(student_record__grade=grade)
    else:
        grade = ""
    if course_id.isdigit() and teacher_courses.filter(pk=course_id).exists():
        students = students.filter(enrollments__course_id=course_id)
    else:
        course_id = ""
    context = {
        "students": Paginator(students.order_by("full_name"), 30).get_page(request.GET.get("page")),
        "grades": grades,
        "courses": teacher_courses.order_by("code"),
        "search": search,
        "grade_filter": grade,
        "course_filter": course_id,
        "requests": EnrollmentChangeRequest.objects.filter(requester=request.user)
        .select_related("course", "student")[:12],
        "recent_changes": PortalAuditEvent.objects.filter(actor=request.user)[:12],
    }
    return render(request, "school/teacher_students.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_assigned_student(request, student_id):
    _require_teacher(request.user)
    student = get_object_or_404(
        User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            enrollments__course__teacher=request.user,
            student_record__isnull=False,
        ).distinct(),
        pk=student_id,
    )
    record = student.student_record
    name_form = TeacherStudentNameForm(request.POST or None, instance=student, prefix="name")
    record_form = TeacherStudentRecordForm(
        request.POST or None,
        instance=record,
        teacher=request.user,
        student=student,
        prefix="record",
    )
    if request.method == "POST" and name_form.is_valid() and record_form.is_valid():
        changed = []
        if name_form.cleaned_data["full_name"] != student.full_name:
            changed.append("name")
        for field in ("grade", "age", "gender"):
            if record_form.cleaned_data[field] != getattr(record, field):
                changed.append(field)
        name_form.save()
        record_form.save()
        if changed:
            record_event(
                request.user,
                "student_school_record_updated",
                "Updated authorized student school-record fields: " + ", ".join(changed) + ".",
                target_name=student.full_name,
            )
            messages.success(request, "Student school record updated and recorded in your activity history.")
        else:
            messages.info(request, "No changes were needed.")
        return redirect("teacher_students")
    return render(
        request,
        "school/teacher_student_edit.html",
        {"student": student, "name_form": name_form, "record_form": record_form},
    )


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def request_enrollment_change(request):
    _require_teacher(request.user)
    form = EnrollmentChangeRequestForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        change = form.save(commit=False)
        change.requester = request.user
        change.requester_name = request.user.full_name
        change.student_name = change.student.full_name
        change.student_email = change.student.email
        try:
            # A nested atomic block provides a savepoint so a duplicate-request
            # constraint error does not poison the enclosing request transaction.
            with transaction.atomic():
                change.save()
        except IntegrityError:
            messages.error(request, "A matching request is already waiting for administrator review.")
        else:
            record_event(
                request.user,
                "enrollment_change_requested",
                f"Requested to {change.get_action_display().lower()} for {change.course.code}.",
                target_name=change.student_name,
            )
            messages.success(request, "Request sent to an administrator. Your class roster was not changed.")
            return redirect("teacher_students")
    return render(
        request,
        "school/teacher_form.html",
        {"form": form, "title": "Request a roster change", "submit_label": "Send request"},
    )
