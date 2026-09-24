"""Role checks shared by the portal's teacher and administrator views."""

from functools import wraps

from django.core.exceptions import PermissionDenied

from .audit import record_role_denial


def require_portal_admin(user, request=None):
    if not user.is_portal_admin:
        record_role_denial(user, "administrator management", request)
        raise PermissionDenied("Only an active Administrator can manage school accounts.")


def require_portal_teacher(user, request=None):
    if not user.is_portal_teacher:
        record_role_denial(user, "teacher student management", request)
        raise PermissionDenied("Only an approved, active Teacher can manage assigned students.")


def portal_admin_view(view_func):
    """Check Administrator access before the view opens its transaction."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        require_portal_admin(request.user, request)
        return view_func(request, *args, **kwargs)

    return wrapped


def portal_teacher_view(view_func):
    """Check Teacher access before the view opens its transaction."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        require_portal_teacher(request.user, request)
        return view_func(request, *args, **kwargs)

    return wrapped
