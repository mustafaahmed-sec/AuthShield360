from django.conf import settings


def auth_mode(request):
    """Expose the current baseline label only while password-only login is active."""
    visible = settings.DEBUG or settings.AUTHSHIELD_PROTECTED_DEMO
    return {"auth_mode_label": "Password-only baseline" if visible else ""}
