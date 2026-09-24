from django.contrib import admin

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
    list_display = ("created_at", "actor_name", "actor_role", "action", "target_name")
    list_filter = ("actor_role", "action", "created_at")
    search_fields = ("actor_name", "actor_email", "target_name", "description")
    readonly_fields = tuple(field.name for field in PortalAuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
