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
    email_enabled = email_otp_available()
    sms_enabled = firebase_phone_auth_available()
    return {
        "enabled": True,
        "sms_enabled": sms_enabled,
        "email_enabled": email_enabled,
        "require_both_factors": email_enabled and sms_enabled,
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


def role_policy_values(role, policy=None):
    """Return editable settings, using safe provider defaults for unmanaged rows."""
    policy = policy or get_role_mfa_policy(role)
    if policy.updated_by_id is None:
        return _role_policy_defaults(role)
    return {
        "enabled": policy.enabled,
        "sms_enabled": policy.sms_enabled,
        "email_enabled": policy.email_enabled,
        "require_both_factors": policy.require_both_factors,
    }


def get_keycloak_mfa_policy():
    policy, _ = KeycloakMFAPolicy.objects.get_or_create(pk=1)
    return policy


def policy_for_user(user):
    """Return the saved role policy filtered through currently available providers."""
    role_policy = get_role_mfa_policy(user.role)
    configured = role_policy_values(user.role, role_policy)
    email_available = email_otp_available()
    sms_available = firebase_phone_auth_available()
    return {
        "enabled": configured["enabled"],
        "sms": configured["sms_enabled"] and sms_available,
        "email": configured["email_enabled"] and email_available,
        "require_both": bool(
            configured["require_both_factors"]
            and configured["sms_enabled"]
            and configured["email_enabled"]
        ),
    }


def allowed_channels(user):
    policy = policy_for_user(user)
    if not policy["enabled"]:
        return []
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
    if phase == "sms_step_up":
        return policy["require_both"] and channel == "sms" and policy["sms"]
    if phase == "email_step_up":
        return policy["require_both"] and channel == "email" and policy["email"]
    if phase == "primary" and policy["require_both"]:
        return channel == "sms" and policy["sms"]
    return channel in allowed_channels(user)


def ensure_method_configuration(form, role, *, sms_available, email_available):
    """Validate methods selected for an enabled role policy."""
    if not form.cleaned_data.get("enabled"):
        return not form.errors
    if form.cleaned_data.get("sms_enabled") and not sms_available:
        form.add_error("sms_enabled", "Firebase Phone Auth is not configured for this deployment.")
    if form.cleaned_data.get("email_enabled") and not email_available:
        form.add_error("email_enabled", "Email OTP delivery is not configured for this deployment.")
    if form.cleaned_data.get("require_both_factors") and not (
        form.cleaned_data.get("sms_enabled") and form.cleaned_data.get("email_enabled")
    ):
        form.add_error("require_both_factors", "Requiring both factors needs SMS and email enabled.")
    if not (form.cleaned_data.get("sms_enabled") or form.cleaned_data.get("email_enabled")):
        form.add_error("email_enabled", f"Enable at least one available second factor for {role_display_name(role).lower()} MFA.")
    return not form.errors


def save_role_policy(role, *, values, actor):
    with transaction.atomic():
        policy = RoleMFAPolicy.objects.select_for_update().get(role=role)
        for field in (
            "enabled", "sms_enabled", "email_enabled", "require_both_factors",
        ):
            setattr(policy, field, values[field])
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
