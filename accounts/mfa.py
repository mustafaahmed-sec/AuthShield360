"""Runtime MFA policy shared by account authentication and the admin controls."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import EmailOTPChallenge, KeycloakMFAPolicy, RoleMFAPolicy, User
from .otp import firebase_phone_auth_available


def email_otp_available():
    """Return whether email OTP has a usable delivery backend in this environment."""
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return True
    return bool(settings.AUTHSHIELD_GMAIL_ADDRESS and settings.AUTHSHIELD_GMAIL_APP_PASSWORD)


def _role_policy_defaults(role):
    configured = settings.AUTHSHIELD_OTP_ENABLED
    email_enabled = configured and email_otp_available()
    sms_enabled = configured and firebase_phone_auth_available()
    require_both = configured and settings.AUTHSHIELD_EMAIL_STEP_UP
    if require_both and not (email_enabled and sms_enabled):
        require_both = False
    return {
        "enabled": configured and (email_enabled or sms_enabled),
        "sms_enabled": sms_enabled,
        "email_enabled": email_enabled,
        "require_both_factors": require_both,
    }


def get_role_mfa_policy(role):
    if role not in User.Role.values:
        raise ValueError("An MFA policy requires a valid portal role.")
    policy, _ = RoleMFAPolicy.objects.get_or_create(
        role=role,
        defaults=_role_policy_defaults(role),
    )
    return policy


def policy_revision_for_user(user):
    """Return the version of the role policy that governs a pending sign-in."""
    return get_role_mfa_policy(user.role).updated_at.isoformat()


def get_portal_mfa_policies():
    return {role: get_role_mfa_policy(role) for role in User.Role.values}


def get_keycloak_mfa_policy():
    policy, _ = KeycloakMFAPolicy.objects.get_or_create(pk=1)
    return policy


def policy_for_user(user):
    """Return effective OTP channels, honoring deployment and provider availability."""
    policy = get_role_mfa_policy(user.role)
    is_legacy_exempt = (
        user.role == User.Role.ADMIN
        and user.email.strip().lower() in settings.AUTHSHIELD_OTP_EXEMPT_EMAILS
        and not policy.include_otp_exempt_accounts
    )
    if not policy.enabled or is_legacy_exempt:
        return {
            "enabled": False,
            "sms": False,
            "email": False,
            "require_both": False,
        }
    return {
        "enabled": True,
        "sms": policy.sms_enabled and firebase_phone_auth_available(),
        "email": policy.email_enabled and email_otp_available(),
        "require_both": policy.require_both_factors,
    }


def allowed_channels(user):
    policy = policy_for_user(user)
    channels = [channel for channel in ("sms", "email") if policy[channel]]
    if policy["require_both"] and set(channels) != {"sms", "email"}:
        return []
    return channels


def initial_channel(user, requested="email"):
    policy = policy_for_user(user)
    channels = allowed_channels(user)
    if not channels:
        return ""
    if policy["require_both"]:
        return "sms"
    return requested if requested in channels else channels[0]


def channel_is_allowed(user, channel, *, phase="primary"):
    policy = policy_for_user(user)
    if not policy["enabled"]:
        return False
    if phase == "email_step_up":
        return policy["require_both"] and channel == "email" and policy["email"]
    return channel in allowed_channels(user)


def ensure_method_configuration(form, role, *, sms_available, email_available):
    """Keep unavailable providers from being enabled through a crafted form post."""
    if form.cleaned_data.get("sms_enabled") and not sms_available:
        form.add_error("sms_enabled", "Firebase Phone Auth is not configured for this deployment.")
    if form.cleaned_data.get("email_enabled") and not email_available:
        form.add_error("email_enabled", "Email OTP delivery is not configured for this deployment.")
    if form.cleaned_data.get("require_both_factors") and not (
        form.cleaned_data.get("sms_enabled") and form.cleaned_data.get("email_enabled")
    ):
        form.add_error("require_both_factors", "Requiring both factors needs SMS and email enabled.")
    if form.cleaned_data.get("enabled") and not (
        form.cleaned_data.get("sms_enabled") or form.cleaned_data.get("email_enabled")
    ):
        form.add_error("enabled", "Choose SMS or email before requiring portal MFA for this role.")
    if not form.cleaned_data.get("enabled") and form.cleaned_data.get("require_both_factors"):
        form.add_error("require_both_factors", "Turn on role MFA before requiring both factors.")
    return not form.errors


def save_role_policy(role, *, values, actor):
    with transaction.atomic():
        policy = RoleMFAPolicy.objects.select_for_update().get(role=role)
        for field in (
            "enabled", "sms_enabled", "email_enabled", "require_both_factors",
        ):
            setattr(policy, field, values[field])
        if role == User.Role.ADMIN:
            policy.include_otp_exempt_accounts = values["include_otp_exempt_accounts"]
        policy.updated_by = actor
        policy.save()
        now = timezone.now()
        EmailOTPChallenge.objects.filter(
            user__role=role,
            purpose__in=(
                EmailOTPChallenge.Purpose.SIGN_IN,
                EmailOTPChallenge.Purpose.EMAIL_STEP_UP,
            ),
            completed_at__isnull=True,
            expires_at__gt=now,
        ).exclude(code_hash="").update(code_hash="", expires_at=now)
    return policy


def provider_readiness():
    return {
        "sms": firebase_phone_auth_available(),
        "email": email_otp_available(),
        "keycloak": settings.AUTHSHIELD_KEYCLOAK_ENABLED,
        "keycloak_admin_api": settings.AUTHSHIELD_KEYCLOAK_ADMIN_API_ENABLED,
    }


def role_display_name(role):
    return dict(User.Role.choices)[role]
