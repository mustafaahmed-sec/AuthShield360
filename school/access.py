"""Role checks shared by the portal's teacher and administrator views."""

from django.core.exceptions import PermissionDenied

from .audit import record_role_denial


def require_portal_admin(user):
    if not user.is_portal_admin:
        record_role_denial(user, "administrator management")
        raise PermissionDenied("Only an active Administrator can manage school accounts.")


def require_portal_teacher(user):
    if not user.is_portal_teacher:
        record_role_denial(user, "teacher student management")
        raise PermissionDenied("Only an approved, active Teacher can manage assigned students.")
