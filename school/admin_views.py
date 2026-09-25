"""Administrator-only account, roster, and activity controls."""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User

from .access import portal_admin_view, require_portal_admin
from .audit import record_event
from .forms import AdminStudentCreationForm
from .models import Enrollment, EnrollmentChangeRequest, PortalAuditEvent, StudentRecord


@login_required
def admin_management(request):
    require_portal_admin(request.user, request)
    search = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
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
    if search:
        accounts = accounts.filter(Q(full_name__icontains=search) | Q(email__icontains=search))
    context = {
        "pending_accounts": Paginator(
            User.objects.filter(
                approval_status=User.ApprovalStatus.PENDING,
                role__in=(User.Role.STUDENT, User.Role.TEACHER),
            ).order_by("date_joined", "pk"),
            20,
        ).get_page(request.GET.get("pending_page")),
        "accounts": Paginator(accounts.select_related("student_record"), 40).get_page(request.GET.get("page")),
        "pending_changes": Paginator(
            EnrollmentChangeRequest.objects.filter(
                status=EnrollmentChangeRequest.Status.PENDING
            ).select_related("requester", "student", "course").order_by("created_at", "pk"),
            20,
        ).get_page(request.GET.get("change_page")),
        "recent_events": PortalAuditEvent.objects.all()[:20],
        "search": search,
        "role_filter": role,
        "status_filter": status,
        "account_page_url": "?" + urlencode({"q": search, "role": role, "status": status}) + "&page=",
        "student_count": User.objects.filter(role=User.Role.STUDENT).count(),
        "teacher_count": User.objects.filter(role=User.Role.TEACHER).count(),
    }
    return render(request, "school/admin_management.html", context)


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
    account.save(update_fields=("is_active",))
    record_event(request.user, f"account_{status_label}", summary, target_name=account.full_name, request=request)
    messages.success(request, f"Access for {account.full_name} was {status_label}.")
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
    record_event(request.user, f"enrollment_request_{status_label}", summary, target_name=change.student_name, request=request)
    messages.success(request, summary)
    return redirect("admin_management")
