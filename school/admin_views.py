"""Administrator-only account, roster, and activity controls."""

from math import ceil
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import OTPDeliveryLimit, User
from accounts.keycloak import (
    KeycloakAdminError,
    keycloak_clear_user_login_failures,
    keycloak_delete_user,
    keycloak_send_password_reset,
    keycloak_set_user_enabled,
)

from .access import portal_admin_view, require_portal_admin
from .audit import record_event
from .forms import AdminAttendanceFilterForm, AdminStudentCreationForm
from .models import (
    Assignment,
    AttendanceRecord,
    Course,
    Enrollment,
    EnrollmentChangeRequest,
    ExamResult,
    PortalAuditEvent,
    StudentRecord,
)


@login_required
def admin_management(request):
    require_portal_admin(request.user, request)
    search = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    now = timezone.now()
    accounts = User.objects.filter(role__in=(User.Role.STUDENT, User.Role.TEACHER)).order_by("role", "full_name")
    if role in (User.Role.STUDENT, User.Role.TEACHER):
        accounts = accounts.filter(role=role)
    if status == "pending":
        accounts = accounts.filter(approval_status=User.ApprovalStatus.PENDING)
    elif status == "rejected":
        accounts = accounts.filter(approval_status=User.ApprovalStatus.REJECTED)
    elif status == "inactive":
        accounts = accounts.filter(is_active=False).exclude(approval_status=User.ApprovalStatus.PENDING)
    elif status == "active":
        accounts = accounts.filter(is_active=True)
    elif status == "locked":
        accounts = accounts.filter(locked_until__gt=now)
    if search:
        accounts = accounts.filter(Q(full_name__icontains=search) | Q(email__icontains=search))
    account_page = Paginator(accounts.select_related("student_record"), 40).get_page(request.GET.get("page"))
    for account in account_page.object_list:
        if account.locked_until and account.locked_until > now:
            account.lockout_remaining_seconds = max(0, ceil((account.locked_until - now).total_seconds()))
            minutes, seconds = divmod(account.lockout_remaining_seconds, 60)
            account.lockout_remaining_display = f"{minutes:02d}:{seconds:02d}"
    admin_accounts = list(User.objects.filter(role=User.Role.ADMIN).order_by("designation", "full_name"))
    _attach_otp_delivery_waits(list(account_page.object_list) + admin_accounts, now)
    context = {
        "keycloak_enabled": settings.AUTHSHIELD_KEYCLOAK_ENABLED,
        "keycloak_admin_api_enabled": settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED,
        "keycloak_admin_console_url": settings.AUTHSHIELD_KEYCLOAK_ADMIN_CONSOLE_URL,
        "pending_accounts": Paginator(
            User.objects.filter(
                approval_status=User.ApprovalStatus.PENDING,
                role__in=(User.Role.STUDENT, User.Role.TEACHER),
            ).order_by("date_joined", "pk"),
            20,
        ).get_page(request.GET.get("pending_page")),
        "accounts": account_page,
        "duplicate_names": set(accounts.values("full_name").annotate(total=Count("id")).filter(total__gt=1).values_list("full_name", flat=True)),
        "pending_changes": Paginator(
            EnrollmentChangeRequest.objects.filter(
                status=EnrollmentChangeRequest.Status.PENDING
            ).select_related("requester", "student", "course").order_by("created_at", "pk"),
            20,
        ).get_page(request.GET.get("change_page")),
        "admin_accounts": admin_accounts,
        "active_otp_delivery_wait_count": sum(
            bool(account.otp_delivery_waits)
            for account in list(account_page.object_list) + admin_accounts
        ),
        "student_events": PortalAuditEvent.objects.filter(actor_role=User.Role.STUDENT)[:20],
        "teacher_events": PortalAuditEvent.objects.filter(actor_role=User.Role.TEACHER)[:20],
        "admin_events": PortalAuditEvent.objects.filter(actor_role=User.Role.ADMIN)[:20],
        "search": search,
        "role_filter": role,
        "status_filter": status,
        "account_page_url": "?" + urlencode({"q": search, "role": role, "status": status}) + "&page=",
        "student_count": User.objects.filter(role=User.Role.STUDENT).count(),
        "teacher_count": User.objects.filter(
            role=User.Role.TEACHER,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        ).count(),
        "active_lockout_count": User.objects.filter(
            role__in=(User.Role.STUDENT, User.Role.TEACHER),
            locked_until__gt=now,
        ).count(),
    }
    return render(request, "school/admin_management.html", context)


def _attach_otp_delivery_waits(accounts, now=None):
    now = now or timezone.now()
    account_ids = [account.pk for account in accounts]
    waits_by_user = {account.pk: [] for account in accounts}
    limits = OTPDeliveryLimit.objects.filter(user_id__in=account_ids).order_by("channel")
    for limit in limits:
        available_at = limit.locked_until if limit.locked_until and limit.locked_until > now else None
        if available_at is None and limit.locked_until and limit.locked_until <= now:
            continue
        if available_at is None and limit.last_requested_at:
            candidate = limit.last_requested_at + timedelta(
                seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS
            )
            if candidate > now:
                available_at = candidate
        if available_at:
            seconds = max(0, ceil((available_at - now).total_seconds()))
            minutes, remainder = divmod(seconds, 60)
            waits_by_user[limit.user_id].append({
                "channel": limit.get_channel_display(),
                "until": available_at.timestamp(),
                "remaining": f"{minutes:02d}:{remainder:02d}",
            })
    for account in accounts:
        account.otp_delivery_waits = waits_by_user.get(account.pk, [])


@login_required
@require_POST
@transaction.atomic
def reset_otp_delivery_lock(request, user_id):
    is_admin = request.user.is_portal_admin
    is_sara = (
        request.user.is_portal_teacher
        and request.user.email.lower() == "sara.ahmed.authshield@gmail.com"
    )
    if not is_admin and not is_sara:
        from .audit import record_role_denial

        record_role_denial(request.user, "OTP delivery lock management", request)
        raise PermissionDenied("Only an Administrator or Sara Ahmed can reset OTP send timers.")

    account = get_object_or_404(User.objects.select_for_update(), pk=user_id)
    if is_sara and (
        account.role != User.Role.STUDENT
        or not account.is_active
        or account.approval_status != User.ApprovalStatus.APPROVED
    ):
        from .audit import record_role_denial

        record_role_denial(request.user, "student OTP delivery lock management", request)
        raise PermissionDenied("Sara Ahmed can reset OTP send timers for approved student accounts only.")
    if account.role not in User.Role.values:
        raise PermissionDenied("OTP send timers can only be reset for portal accounts.")

    now = timezone.now()
    waits = list(OTPDeliveryLimit.objects.select_for_update().filter(user=account))
    active_wait = any(
        (limit.locked_until and limit.locked_until > now)
        or (
            limit.last_requested_at
            and limit.last_requested_at + timedelta(seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS) > now
        )
        for limit in waits
    )
    if not active_wait:
        messages.error(request, f"{account.full_name} has no active OTP send timer to reset.")
    else:
        OTPDeliveryLimit.objects.filter(user=account).update(
            request_count=0,
            last_requested_at=None,
            locked_until=None,
        )
        record_event(
            request.user,
            "otp_delivery_lock_reset",
            "Reset the account's email and SMS code-send cooldowns. Password lockouts and invalid-code attempt counters were not changed.",
            target_name=account.email,
            request=request,
            factor=PortalAuditEvent.Factor.ACCESS,
            outcome=PortalAuditEvent.Outcome.SUCCESS,
        )
        messages.success(request, f"OTP send timers cleared for {account.full_name}. They can request a new code.")

    return redirect("admin_management" if is_admin else "teacher_students")


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def unlock_school_account(request, user_id):
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
    )
    local_lockout_active = bool(account.locked_until and account.locked_until > timezone.now())
    can_clear_keycloak_failures = bool(
        settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED and account.keycloak_subject
    )
    if not local_lockout_active and not can_clear_keycloak_failures:
        messages.error(request, f"{account.full_name} does not have an active sign-in lockout.")
        return redirect("admin_management")

    if can_clear_keycloak_failures:
        try:
            keycloak_clear_user_login_failures(account.keycloak_subject)
        except KeycloakAdminError:
            messages.error(request, "Keycloak could not clear this user's sign-in failures. No portal lockout was changed.")
            return redirect("admin_management")

    if account.locked_until:
        account.locked_until = None
        account.save(update_fields=("locked_until",))
    record_event(
        request.user,
        "account_unlocked",
        "Cleared portal and Keycloak failed-login lock state so the account holder can try signing in again.",
        target_name=account.email,
        request=request,
        factor=PortalAuditEvent.Factor.ACCESS,
        outcome=PortalAuditEvent.Outcome.SUCCESS,
    )
    messages.success(request, f"Sign-in lockout cleared for {account.full_name}. They can try signing in again.")
    return redirect("admin_management")


@login_required
@portal_admin_view
def admin_attendance(request):
    form = AdminAttendanceFilterForm(request.GET or None)
    records = AttendanceRecord.objects.select_related("course", "student", "marked_by")
    if form.is_valid():
        search = form.cleaned_data["search"]
        if search:
            records = records.filter(
                Q(student__full_name__icontains=search)
                | Q(student__email__icontains=search)
                | Q(course__code__icontains=search)
                | Q(course__title__icontains=search)
            )
        if form.cleaned_data["course"]:
            records = records.filter(course=form.cleaned_data["course"])
        if form.cleaned_data["date"]:
            records = records.filter(date=form.cleaned_data["date"])
        if form.cleaned_data["status"]:
            records = records.filter(status=form.cleaned_data["status"])
    records = records.order_by("-date", "course__code", "student__full_name")
    filters = {key: value for key, value in request.GET.items() if key in {"search", "course", "date", "status"}}
    context = {
        "form": form,
        "records": Paginator(records, 30).get_page(request.GET.get("page")),
        "record_count": records.count(),
        "page_url": "?" + urlencode(filters) + ("&" if filters else "") + "page=",
        "advanced_attendance_url": "admin:school_attendancerecord_changelist",
    }
    return render(request, "school/admin_attendance.html", context)


@login_required
@portal_admin_view
def preview_school_portal(request, user_id):
    target = get_object_or_404(
        User.objects.select_related("student_record"),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
    )
    record_event(
        request.user,
        "portal_preview_opened",
        f"Opened a read-only {target.get_role_display().lower()} portal preview; no account session was changed.",
        target_name=target.full_name,
        request=request,
    )
    context = {"target": target}
    if target.role == User.Role.TEACHER:
        courses = list(Course.objects.filter(teacher=target).order_by("code"))
        enrollments = list(
            Enrollment.objects.filter(course__teacher=target)
            .select_related("student", "course", "student__student_record")
            .order_by("course__code", "student__full_name")[:60]
        )
        course_rosters = [
            {
                "course": course,
                "students": [enrollment for enrollment in enrollments if enrollment.course_id == course.pk],
            }
            for course in courses
        ]
        context.update({
            "courses": courses,
            "enrollments": enrollments,
            "course_rosters": course_rosters,
            "assignments": Assignment.objects.filter(course__teacher=target)
            .select_related("course").order_by("course__code", "due_date", "pk")[:30],
            "results": ExamResult.objects.filter(course__teacher=target)
            .select_related("student", "course").order_by("exam_name", "course__code", "student__full_name")[:40],
            "attendance_count": AttendanceRecord.objects.filter(course__teacher=target).count(),
        })
    else:
        courses = Course.objects.filter(enrollments__student=target).select_related("teacher").order_by("code")
        context.update({
            "record": getattr(target, "student_record", None),
            "courses": courses,
            "recent_attendance": AttendanceRecord.objects.filter(student=target)
            .select_related("course").order_by("-date", "course__code")[:15],
            "assignments": Assignment.objects.filter(course__enrollments__student=target)
            .select_related("course").order_by("due_date", "pk")[:30],
            "results": ExamResult.objects.filter(student=target)
            .select_related("course").order_by("course__code", "exam_name")[:30],
            "attendance_count": AttendanceRecord.objects.filter(student=target).count(),
        })
    return render(request, "school/admin_portal_preview.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@portal_admin_view
def add_student(request):
    form = AdminStudentCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            student = form.save(reviewed_by=request.user)
            StudentRecord.objects.create(
                student=student,
                admission_number=f"AS-A{student.pk:06d}",
                grade=form.cleaned_data["grade"],
                age=form.cleaned_data["age"],
            )
            record_event(
                request.user,
                "student_account_created",
                "Created an approved Student account and school record.",
                target_name=student.full_name,
                request=request,
            )
        messages.success(request, f"Student account created for {student.full_name}. They can now sign in.")
        return redirect("admin_management")
    return render(request, "school/admin_add_student.html", {"form": form})


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def review_account_request(request, user_id):
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
        approval_status__in=(User.ApprovalStatus.PENDING, User.ApprovalStatus.REJECTED),
    )
    action = request.POST.get("action")
    if action == "approve" and settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED:
        if not account.keycloak_subject:
            messages.error(request, "This request has no linked Keycloak identity. Have the applicant register through Keycloak first.")
            return redirect("admin_management")
        try:
            keycloak_set_user_enabled(account.keycloak_subject, True)
        except KeycloakAdminError:
            messages.error(request, "Keycloak could not enable this identity. The access request was not changed.")
            return redirect("admin_management")
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
    record_event(request.user, f"account_request_{status_label}", summary, target_name=account.full_name, request=request)
    messages.success(request, f"{account.get_role_display()} request for {account.full_name} was {status_label}.")
    return redirect("admin_management")


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def change_account_access(request, user_id):
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
    if settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED and account.keycloak_subject:
        try:
            keycloak_set_user_enabled(account.keycloak_subject, action == "reactivate")
        except KeycloakAdminError:
            messages.error(request, "Keycloak could not update this account. Its access was not changed.")
            return redirect("admin_management")
    account.save(update_fields=("is_active",))
    record_event(request.user, f"account_{status_label}", summary, target_name=account.full_name, request=request)
    messages.success(request, f"Access for {account.full_name} was {status_label}.")
    return redirect("admin_management")


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def reset_school_account_password(request, user_id):
    account = get_object_or_404(User.objects.select_for_update(), pk=user_id, role__in=(User.Role.STUDENT, User.Role.TEACHER), is_active=True)
    if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        if not settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED or not account.keycloak_subject:
            messages.error(request, "Connect the Keycloak admin service account before resetting this password.")
            return redirect("admin_management")
        try:
            keycloak_send_password_reset(account.keycloak_subject)
        except KeycloakAdminError:
            messages.error(request, "Keycloak could not send the password update email.")
            return redirect("admin_management")
        account.must_change_password = False
        account.save(update_fields=("must_change_password",))
        record_event(request.user, "account_password_reset", "Sent a Keycloak password update email.", target_name=account.full_name, request=request, factor="password", outcome="success")
        messages.success(request, f"Keycloak sent a password update email to {account.email}.")
        return redirect("admin_management")
    temporary_password = get_random_string(20, allowed_chars="abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789") + "!"
    account.set_password(temporary_password)
    account.must_change_password = True
    account.save(update_fields=("password", "must_change_password"))
    record_event(request.user, "account_password_reset", "Generated a one-time temporary password; the account holder must replace it at next sign-in.", target_name=account.full_name, request=request, factor="password", outcome="success")
    messages.success(request, f"Temporary password for {account.full_name} ({account.email}): {temporary_password}. Share it privately; it will be replaced at first sign-in.")
    return redirect("admin_management")


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def delete_school_account(request, user_id):
    account = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
        role__in=(User.Role.STUDENT, User.Role.TEACHER),
    )
    label = account.full_name
    email = account.email
    role_label = account.get_role_display().lower()
    if settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED and account.keycloak_subject:
        try:
            keycloak_delete_user(account.keycloak_subject)
        except KeycloakAdminError:
            messages.error(request, "Keycloak could not delete this identity. The portal account was not removed.")
            return redirect("admin_management")
    record_event(
        request.user,
        "school_account_deleted",
        f"Deleted the {role_label} account {email}; linked academic records follow their configured retention rules.",
        target_name=label,
        request=request,
    )
    account.delete()
    messages.success(request, f"The account for {label} was deleted.")
    return redirect("admin_management")


@login_required
@require_POST
@portal_admin_view
@transaction.atomic
def review_enrollment_request(request, request_id):
    change = get_object_or_404(
        EnrollmentChangeRequest.objects.select_for_update(of=("self",)).select_related("student", "course"),
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
            if not Enrollment.objects.filter(student=change.student, course=change.course).exists():
                enrollment = Enrollment(student=change.student, course=change.course)
                try:
                    enrollment.full_clean()
                except ValidationError as error:
                    messages.error(request, f"The roster was not changed: {error.messages[0]}")
                    return redirect("admin_management")
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
    record_event(request.user, f"enrollment_request_{status_label}", summary, target_name=change.student_name, request=request)
    messages.success(request, summary)
    return redirect("admin_management")




