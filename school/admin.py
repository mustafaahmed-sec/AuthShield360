import csv

from django import forms
from django.contrib import admin
from django.db.models import Q
from django.http import HttpResponse

from accounts.models import User

from .models import Assignment, AttendanceRecord, Course, Enrollment, EnrollmentChangeRequest, ExamResult, PortalAuditEvent, StudentRecord
from . import announcement_admin  # noqa: F401


class AttendanceRecordAdminForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        student_field = self.fields["student"]
        student_field.error_messages["invalid_choice"] = (
            "That student is not enrolled in the selected course. Add the student to the course roster first."
        )
        students = User.objects.filter(role=User.Role.STUDENT)
        course_id = (
            self.data.get(self.add_prefix("course"))
            if self.is_bound
            else self.initial.get("course") or getattr(self.instance, "course_id", None)
        )
        if course_id:
            eligible_student = Q(enrollments__course_id=course_id)
            if self.instance.pk and self.instance.student_id:
                eligible_student |= Q(pk=self.instance.student_id)
            students = students.filter(eligible_student)
        student_field.queryset = students.distinct().order_by("full_name", "email")

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        student = cleaned.get("student")
        day = cleaned.get("date")
        if course and student and day and self.instance._state.adding:
            exists = AttendanceRecord.objects.filter(course=course, student=student, date=day).exists()
            if exists:
                self.add_error("date", "An attendance record already exists for this student, course, and date.")
        return cleaned


@admin.register(StudentRecord)
class StudentRecordAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "student", "grade", "age", "gender")
    search_fields = ("admission_number", "student__email", "student__full_name")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "teacher")
    search_fields = ("code", "title", "teacher__email")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course")
    list_filter = ("course",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "due_date")
    list_filter = ("course",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    form = AttendanceRecordAdminForm
    list_display = ("date", "course", "student", "status", "marked_by", "updated_at")
    list_filter = ("date", "status", "course")
    search_fields = ("student__full_name", "student__email", "course__code")
    readonly_fields = ("updated_at",)
    list_select_related = ("course", "student", "marked_by")

    def save_model(self, request, obj, form, change):
        if not change and obj.marked_by_id is None:
            obj.marked_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "exam_name", "score", "max_score")
    list_filter = ("course",)


@admin.register(EnrollmentChangeRequest)
class EnrollmentChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("student_name", "course", "action", "status", "requester_name", "created_at")
    list_filter = ("status", "action", "course")
    search_fields = ("student_name", "student_email", "requester_name", "course__code")
    readonly_fields = ("created_at", "reviewed_at")


@admin.register(PortalAuditEvent)
class PortalAuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_name", "actor_role", "auth_mode", "factor", "outcome", "action", "target_name")
    list_filter = ("actor_role", "created_at", "factor", "outcome", "auth_mode")
    search_fields = ("actor_name", "actor_email", "target_name", "description")
    readonly_fields = tuple(field.name for field in PortalAuditEvent._meta.fields)
    actions = ("export_selected_as_csv",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_authenticated and request.user.is_portal_admin

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None and request.user.is_authenticated and request.user.is_portal_admin

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Export selected as CSV")
    def export_selected_as_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="authshield-audit-events.csv"'
        writer = csv.writer(response)
        fields = (
            "created_at", "actor_email", "actor_role", "auth_mode", "factor", "outcome",
            "ip_address", "session_hint", "duration_ms", "action", "target_name", "description",
        )
        writer.writerow(fields)
        for event in queryset.order_by("created_at", "pk"):
            row = []
            for field in fields:
                value = getattr(event, field, "")
                value = value.isoformat() if hasattr(value, "isoformat") else str(value or "")
                if value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    value = "'" + value
                row.append(value)
            writer.writerow(row)
        return response
