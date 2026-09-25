"""Teacher actions limited to assigned courses and students."""

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import User

from .access import portal_teacher_view, require_portal_teacher
from .audit import record_event
from .forms import (
    AttendanceSelectionForm,
    AttendanceSheetForm,
    EnrollmentChangeRequestForm,
    TeacherAssignmentForm,
    TeacherExamResultForm,
    TeacherStudentNameForm,
    TeacherStudentRecordForm,
)
from .models import AttendanceRecord, Course, Enrollment, EnrollmentChangeRequest, PortalAuditEvent, StudentRecord


@login_required
@require_http_methods(["GET", "POST"])
@portal_teacher_view
def teacher_attendance(request):
    courses = Course.objects.filter(teacher=request.user).order_by("code")
    first_course = courses.first()
    initial = {"course": first_course.pk, "date": timezone.localdate()} if first_course else {}
    selection_form = AttendanceSelectionForm(
        request.POST if request.method == "POST" else (request.GET if request.GET else None),
        teacher=request.user,
        initial=initial,
    )
    course = first_course if not selection_form.is_bound else None
    day = timezone.localdate() if not selection_form.is_bound else None
    if selection_form.is_bound and selection_form.is_valid():
        course = selection_form.cleaned_data["course"]
        day = selection_form.cleaned_data["date"]

    rows = []
    sheet_form = None
    if course and day:
        students = list(
            User.objects.filter(
                role=User.Role.STUDENT,
                is_active=True,
                approval_status=User.ApprovalStatus.APPROVED,
                enrollments__course=course,
            ).order_by("full_name", "pk")
        )
        current = {
            record.student_id: record
            for record in AttendanceRecord.objects.filter(course=course, date=day, student__in=students)
        }
        sheet_form = AttendanceSheetForm(
            request.POST if request.method == "POST" else None,
            students=students,
            current=current,
        )
        rows = [(student, sheet_form[f"status_{student.pk}"]) for student in students]
        if request.method == "POST" and sheet_form.is_valid():
            changed = 0
            with transaction.atomic():
                for student in students:
                    status = sheet_form.cleaned_data[f"status_{student.pk}"]
                    previous = current.get(student.pk)
                    if previous and previous.status == status:
                        continue
                    if not status:
                        if previous:
                            previous.delete()
                            changed += 1
                    else:
                        AttendanceRecord.objects.update_or_create(
                            course=course, student=student, date=day,
                            defaults={"status": status, "marked_by": request.user},
                        )
                        changed += 1
                if changed:
                    record_event(
                        request.user, "attendance_saved",
                        f"Updated {changed} attendance record(s) for {course.code} on {day.isoformat()}.",
                        target_name=course.code, request=request,
                    )
            if changed:
                messages.success(request, f"Attendance saved for {course.code}: {changed} record(s) updated.")
            else:
                messages.info(request, "No attendance changes were needed.")
            return redirect(reverse("teacher_attendance") + "?" + urlencode({"course": course.pk, "date": day.isoformat()}))

    return render(request, "school/teacher_attendance.html", {
        "selection_form": selection_form,
        "sheet_form": sheet_form,
        "rows": rows,
        "course": course,
        "day": day,
        "has_courses": bool(first_course),
    })


@login_required
@require_http_methods(["GET", "POST"])
def create_assignment(request):
    require_portal_teacher(request.user, request)
    form = TeacherAssignmentForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        assignment = form.save()
        record_event(
            request.user,
            "assignment_created",
            f"Created assignment {assignment.title} for {assignment.course.code}.",
            target_name=assignment.title,
            request=request,
        )
        messages.success(request, "Assignment saved for your course.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Create assignment", "submit_label": "Save assignment"})


@login_required
@require_http_methods(["GET", "POST"])
def create_exam_result(request):
    require_portal_teacher(request.user, request)
    form = TeacherExamResultForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        result = form.save()
        record_event(
            request.user,
            "exam_result_recorded",
            f"Recorded a result for {result.exam_name} in {result.course.code}.",
            target_name=result.student.full_name,
            request=request,
        )
        messages.success(request, "Exam result saved for an enrolled student.")
        return redirect("dashboard")
    return render(request, "school/teacher_form.html", {"form": form, "title": "Record exam result", "submit_label": "Save result"})


@login_required
def teacher_students(request):
    require_portal_teacher(request.user, request)
    teacher_courses = Course.objects.filter(teacher=request.user, teacher__is_active=True)
    roster = User.objects.filter(
        role=User.Role.STUDENT,
        is_active=True,
        student_record__isnull=False,
    ).select_related("student_record").prefetch_related(
        Prefetch(
            "enrollments",
            queryset=Enrollment.objects.filter(course__teacher=request.user).select_related("course"),
        )
    )
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
        "student_page_url": "?" + urlencode({"q": search, "grade": grade, "course": course_id}) + "&page=",
        "requests": EnrollmentChangeRequest.objects.filter(requester=request.user)
        .select_related("course", "student")[:12],
        "recent_changes": PortalAuditEvent.objects.filter(actor=request.user)[:12],
    }
    return render(request, "school/teacher_students.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@portal_teacher_view
@transaction.atomic
def edit_assigned_student(request, student_id):
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
        if "full_name" in name_form.changed_data:
            changed.append("name")
        for field in record_form.changed_data:
            if field in ("grade", "age", "gender"):
                changed.append(field)
        name_form.save()
        record_form.save()
        if changed:
            record_event(
                request.user,
                "student_school_record_updated",
                "Updated authorized student school-record fields: " + ", ".join(changed) + ".",
                target_name=student.full_name,
                request=request,
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
@portal_teacher_view
@transaction.atomic
def request_enrollment_change(request):
    form = EnrollmentChangeRequestForm(request.POST or None, teacher=request.user)
    if request.method == "POST" and form.is_valid():
        change = form.save(commit=False)
        change.student = form.cleaned_data["student"]
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
                request=request,
            )
            messages.success(request, "Request sent to an administrator. Your class roster was not changed.")
            return redirect("teacher_students")
    return render(
        request,
        "school/teacher_form.html",
        {"form": form, "title": "Request a roster change", "submit_label": "Send request"},
    )
