import os

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


def static_version(request):
    """Give browsers a new asset URL whenever Vercel builds a new commit."""
    revision = (
        os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
        or os.environ.get("VERCEL_URL", "").strip()
        or "local"
    )
    return {"static_version": revision[:12]}
