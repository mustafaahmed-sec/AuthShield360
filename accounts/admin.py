from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from school.audit import record_event

from .models import User


@admin.register(User)
class AuthShieldUserAdmin(UserAdmin):
    model = User
    list_display = ("email", "full_name", "role", "approval_status", "is_active", "locked_until", "is_staff")
    list_filter = ("role", "approval_status", "is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    readonly_fields = ("locked_until",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("full_name", "phone_number", "role")}),
        ("Access review", {"fields": ("approval_status", "reviewed_at", "reviewed_by", "locked_until")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "phone_number", "role", "usable_password", "password1", "password2")}),
    )

    actions = ("unlock_selected_accounts",)

    @admin.action(description="Unlock selected accounts")
    def unlock_selected_accounts(self, request, queryset):
        unlocked = 0
        accounts = queryset.exclude(locked_until__isnull=True)
        for account in accounts:
            account.locked_until = None
            account.save(update_fields=("locked_until",))
            record_event(
                request.user,
                "account_unlocked",
                "Cleared the temporary failed-login lock for an account.",
                target_name=account.email,
                request=request,
                factor="access",
                outcome="success",
            )
            unlocked += 1
        self.message_user(
            request,
            f"Unlocked {unlocked} account(s)." if unlocked else "No selected account was locked.",
            level=messages.SUCCESS if unlocked else messages.INFO,
        )

    def has_delete_permission(self, request, obj=None):
        allowed = super().has_delete_permission(request, obj)
        return allowed and (obj is None or obj.role in (User.Role.STUDENT, User.Role.TEACHER))

    def delete_model(self, request, obj):
        record_event(
            request.user,
            "school_account_deleted",
            f"Deleted the {obj.get_role_display().lower()} account {obj.email}; linked academic records follow their configured retention rules.",
            target_name=obj.full_name,
            request=request,
            factor="access",
            outcome="success",
        )
        super().delete_model(request, obj)
