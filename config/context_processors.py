from django.conf import settings


def auth_mode(request):
    """Show the authentication stage currently configured for the portal."""
    visible = settings.DEBUG or settings.AUTHSHIELD_PROTECTED_DEMO
    if not visible:
        label = ""
    elif settings.AUTHSHIELD_OTP_ENABLED:
        label = "Email OTP sign-in" if not settings.AUTHSHIELD_EMAIL_STEP_UP else "OTP sign-in"
    else:
        label = "Password-only baseline"
    return {"auth_mode_label": label}
