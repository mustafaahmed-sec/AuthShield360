import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import Assignment, Course, Enrollment, EnrollmentChangeRequest, ExamResult, PortalAuditEvent, StudentRecord


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
