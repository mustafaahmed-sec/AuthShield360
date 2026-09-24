from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from school.audit import record_event

from .models import User


@admin.register(User)
class AuthShieldUserAdmin(UserAdmin):
    model = User
    list_display = ("email", "full_name", "role", "approval_status", "is_active", "is_staff")
    list_filter = ("role", "approval_status", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("full_name", "phone_number", "role")}),
        ("Access review", {"fields": ("approval_status", "reviewed_at", "reviewed_by")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "phone_number", "role", "usable_password", "password1", "password2")}),
    )

    actions = None

    def has_delete_permission(self, request, obj=None):
        allowed = super().has_delete_permission(request, obj)
        return allowed and (obj is None or obj.role in (User.Role.STUDENT, User.Role.TEACHER))

    def delete_model(self, request, obj):
        record_event(
            request.user,
            "school_account_deleted",
            f"Deleted the {obj.get_role_display().lower()} account {obj.email}; linked academic records follow their configured retention rules.",
            target_name=obj.full_name,
        )
        super().delete_model(request, obj)
