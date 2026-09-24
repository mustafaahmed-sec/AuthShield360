from django.conf import settings
from django.contrib.admin.apps import AdminConfig
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache


class AuthShieldAdminSite(AdminSite):
    site_header = "AuthShield 360 administration"
    site_title = "AuthShield 360"
    index_title = "Fictional school data"

    def has_permission(self, request):
        user = request.user
        allowed = (
            user.is_active
            and user.is_staff
            and user.is_superuser
            and getattr(user, "role", None) == "admin"
        )
        if user.is_authenticated and not allowed:
            from school.audit import record_role_denial

            record_role_denial(user, "Django administrator")
        return allowed

    @method_decorator(never_cache)
    def login(self, request, extra_context=None):
        if not settings.AUTHSHIELD_BASELINE_LOGIN_ENABLED:
            raise PermissionDenied("Administrator sign-in is disabled with the password-only baseline.")
        if request.user.is_authenticated:
            if self.has_permission(request):
                return super().login(request, extra_context)
            raise PermissionDenied("Only an Administrator can access Django administration.")
        # Keep all password authentication on the portal's shared login route,
        # so this separate Django endpoint cannot become an MFA bypass later.
        return redirect("login")


class AuthShieldAdminConfig(AdminConfig):
    default_site = "config.admin.AuthShieldAdminSite"
