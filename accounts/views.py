import hashlib
import hmac
import logging
import time
from datetime import timedelta
from math import ceil
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ImproperlyConfigured, NON_FIELD_ERRORS, PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required

from .lockout import (
    account_lockout_until,
    clear_expired_or_successful_lock,
    ip_throttle_until,
    normalized_email,
    consume_public_request_quota,
    record_blocked_attempt,
    record_failed_authentication,
    retry_minutes,
)

from .forms import (
    EmailAuthenticationForm,
    KeycloakAccessRequestForm,
    PasswordResetRequestForm,
    RegistrationStatusForm,
    StudentSignupForm,
    TeacherSignupForm,
)
from .keycloak import keycloak_client
from .mfa import (
    allowed_channels,
    channel_is_allowed,
    initial_channel,
    policy_for_user,
    policy_revision_for_user,
)
from django.contrib.auth.forms import SetPasswordForm
from .models import EmailOTPChallenge, OTPDeliveryLimit, PasswordResetRequestLimit, SMSOTPDeliveryLimit
from .otp import (
    OTPChallengeChanged,
    OTPChallengeExpired,
    OTPProviderError,
    MAX_OTP_ATTEMPTS,
    check_otp,
    delivery_target,
    firebase_phone_auth_available,
    start_otp,
    verify_firebase_phone_id_token,
)
from .throttling import consume_throttle_quota
from school.audit import record_auth_event, request_ip


User = get_user_model()
logger = logging.getLogger("authshield.keycloak")
REGISTRATION_SUBMISSION_MESSAGE = (
    "If this address can be used for an access request, the request has been received. "
    "If you already have an account or request, check its status."
)
OTP_SESSION_KEYS = (
    "authshield_otp_user_id",
    "authshield_otp_channel",
    "authshield_otp_phase",
    "authshield_otp_primary_channel",
    "authshield_otp_next",
    "authshield_otp_sent_at",
    "authshield_otp_expires_at",
    "authshield_otp_started_at",
    "authshield_otp_attempts",
    "authshield_otp_resends",
    "authshield_otp_policy_revision",
    "authshield_otp_sms_sent_at",
    "authshield_otp_sms_send_authorized_at",
    "authshield_otp_sms_sent",
    "authshield_otp_expiry_logged",
    "authshield_email_otp_hash",
)


def _clear_otp_session(request):
    for key in OTP_SESSION_KEYS:
        request.session.pop(key, None)


def _otp_policy_is_current(request, user):
    return request.session.get("authshield_otp_policy_revision") == policy_revision_for_user(user)


def _otp_ttl_seconds(channel):
    if channel == "email":
        return settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
    if channel == "sms":
        return settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    return settings.AUTHSHIELD_OTP_TTL_SECONDS


class OTPDeliveryRateLimited(Exception):
    def __init__(self, available_at):
        self.available_at = available_at


def _otp_delivery_available_at(user, channel, now=None):
    now = now or timezone.now()
    limit = OTPDeliveryLimit.objects.filter(user=user, channel=channel).first()
    if not limit:
        return now
    if limit.locked_until and limit.locked_until > now:
        return limit.locked_until
    if limit.locked_until and limit.locked_until <= now:
        return now
    if limit.last_requested_at:
        cooldown_ends = limit.last_requested_at + timedelta(
            seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS
        )
        if cooldown_ends > now:
            return cooldown_ends
    return now


def _otp_wait_label(available_at, now=None):
    now = now or timezone.now()
    seconds = max(1, ceil((available_at - now).total_seconds()))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes:02d}:{remainder:02d}"


def _reserve_otp_delivery(user, channel, now=None):
    """Consume one persistent send attempt or return when another send is allowed."""
    now = now or timezone.now()
    with transaction.atomic():
        limit, _ = OTPDeliveryLimit.objects.get_or_create(
            user=user,
            channel=channel,
        )
        limit = OTPDeliveryLimit.objects.select_for_update().get(pk=limit.pk)
        if limit.locked_until and limit.locked_until > now:
            return False, limit.locked_until
        if limit.locked_until and limit.locked_until <= now:
            limit.request_count = 0
            limit.locked_until = None
            limit.last_requested_at = None
        if limit.last_requested_at:
            cooldown_ends = limit.last_requested_at + timedelta(
                seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS
            )
            if cooldown_ends > now:
                return False, cooldown_ends
        if limit.request_count >= settings.AUTHSHIELD_OTP_MAX_SENDS:
            limit.locked_until = now + timedelta(minutes=settings.AUTHSHIELD_OTP_SEND_LOCKOUT_MINUTES)
            limit.save(update_fields=("request_count", "locked_until", "last_requested_at"))
            return False, limit.locked_until
        limit.request_count += 1
        limit.last_requested_at = now
        if limit.request_count >= settings.AUTHSHIELD_OTP_MAX_SENDS:
            limit.locked_until = now + timedelta(minutes=settings.AUTHSHIELD_OTP_SEND_LOCKOUT_MINUTES)
        limit.save(update_fields=("request_count", "last_requested_at", "locked_until"))
        return True, limit.locked_until or (
            now + timedelta(seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS)
        )


def _start_otp(request, user, channel, *, phase="primary", reset_resends=True, force_new=False):
    purpose = "email_step_up" if phase == "email_step_up" else "sign_in"
    policy_revision = policy_revision_for_user(user)
    active_challenge = (
        not force_new
        and channel == "email"
        and EmailOTPChallenge.objects.filter(
            user=user,
            purpose=purpose,
            code_hash__gt="",
            expires_at__gt=timezone.now(),
            completed_at__isnull=True,
        ).exists()
    )
    if not active_challenge:
        allowed, available_at = _reserve_otp_delivery(user, channel)
        if not allowed:
            raise OTPDeliveryRateLimited(available_at)
    challenge = start_otp(
        delivery_target(user, channel),
        channel,
        request.session,
        recipient_name=user.full_name,
        user=user,
        purpose=purpose,
        force_new=force_new,
    )
    request.session["authshield_otp_user_id"] = user.pk
    request.session["authshield_otp_channel"] = channel
    request.session["authshield_otp_phase"] = phase
    request.session["authshield_otp_policy_revision"] = policy_revision
    if phase == "primary":
        request.session["authshield_otp_primary_channel"] = channel
    now = timezone.now().timestamp()
    sent_at = challenge.sent_at.timestamp() if isinstance(challenge, EmailOTPChallenge) and challenge.sent_at else now
    request.session["authshield_otp_sent_at"] = sent_at
    ttl_seconds = _otp_ttl_seconds(channel)
    expires_at = challenge.expires_at.timestamp() if isinstance(challenge, EmailOTPChallenge) and challenge.expires_at else now + ttl_seconds
    request.session["authshield_otp_expires_at"] = expires_at
    request.session["authshield_otp_started_at"] = sent_at
    request.session["authshield_otp_attempts"] = 0
    request.session.pop("authshield_otp_expiry_logged", None)
    if reset_resends:
        request.session["authshield_otp_resends"] = 0
    # Keep the pending sign-in session alive after a code expires so the user
    # can request a replacement without entering their password again.
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    return challenge


def _prepare_firebase_sms_challenge(request, user, *, phase="primary"):
    if not firebase_phone_auth_available():
        raise ImproperlyConfigured("Firebase Phone Authentication is not configured.")
    if not delivery_target(user, "sms"):
        raise OTPProviderError("This account has no valid international phone number.")
    next_url = request.session.get("authshield_otp_next")
    _clear_otp_session(request)
    now = timezone.now().timestamp()
    request.session["authshield_otp_user_id"] = user.pk
    request.session["authshield_otp_channel"] = "sms"
    request.session["authshield_otp_phase"] = phase
    request.session["authshield_otp_primary_channel"] = "email" if phase == "sms_step_up" else "sms"
    if next_url:
        request.session["authshield_otp_next"] = next_url
    request.session["authshield_otp_policy_revision"] = policy_revision_for_user(user)
    request.session["authshield_otp_started_at"] = now
    request.session["authshield_otp_expires_at"] = now + settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    request.session["authshield_otp_attempts"] = 0
    request.session["authshield_otp_resends"] = 0
    request.session["authshield_otp_sms_sent"] = False
    request.session.pop("authshield_otp_expiry_logged", None)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)


def _otp_duration_ms(request):
    started_at = request.session.get("authshield_otp_started_at")
    if started_at is None:
        return None
    return max(0, int((timezone.now().timestamp() - started_at) * 1000))


def _sync_email_otp_challenge(request, user, phase):
    """Keep tabs using the same account challenge on the current code and timer."""
    purpose = "email_step_up" if phase == "email_step_up" else "sign_in"
    challenge = EmailOTPChallenge.objects.filter(user=user, purpose=purpose).first()
    if not challenge:
        return False, False
    if challenge.completed_at:
        return False, True
    if not challenge.sent_at or not challenge.expires_at:
        return False, False

    latest_sent_at = challenge.sent_at.timestamp()
    session_sent_at = request.session.get("authshield_otp_sent_at")
    replaced = (
        session_sent_at is not None
        and abs(float(session_sent_at) - latest_sent_at) > 0.001
    )
    if session_sent_at is None or replaced:
        request.session["authshield_otp_sent_at"] = latest_sent_at
        request.session["authshield_otp_expires_at"] = challenge.expires_at.timestamp()
        request.session["authshield_otp_started_at"] = latest_sent_at
        request.session["authshield_otp_attempts"] = challenge.attempts
        request.session.pop("authshield_otp_expiry_logged", None)
    return replaced, False


def _otp_context(request, user, channel, phase):
    destination = delivery_target(user, channel)
    if channel == "email":
        local, _, domain = destination.partition("@")
        destination = f"{local[:1]}***@{domain}" if domain else "your email address"
    else:
        destination = f"••••{destination[-4:]}" if len(destination) >= 4 else "your phone number"
    context = {
        "channel": channel,
        "destination": destination,
        "phase": phase,
        "step_up": phase in {"sms_step_up", "email_step_up"},
        "requires_both_factors": policy_for_user(user)["require_both"],
        "otp_sms_sent": channel != "sms" or bool(request.session.get("authshield_otp_sms_sent")),
        "otp_expires_at": request.session.get("authshield_otp_expires_at", 0),
        "otp_resend_available_at": _otp_delivery_available_at(user, channel).timestamp(),
    }
    if channel == "sms":
        context.update({
            "firebase_phone_config": {
                "apiKey": settings.AUTHSHIELD_FIREBASE_API_KEY,
                "authDomain": settings.AUTHSHIELD_FIREBASE_AUTH_DOMAIN,
                "projectId": settings.AUTHSHIELD_FIREBASE_PROJECT_ID,
                "appId": settings.AUTHSHIELD_FIREBASE_APP_ID,
                "appCheckSiteKey": settings.AUTHSHIELD_FIREBASE_APPCHECK_SITE_KEY,
            },
            "firebase_phone_number": delivery_target(user, "sms"),
        })
    return context


def signup(request, role="student"):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form_class, role_label = {
        "student": (StudentSignupForm, "student"),
        "teacher": (TeacherSignupForm, "teacher"),
    }.get(role, (None, None))
    if form_class is None:
        raise PermissionDenied("Public registration is available for Student and Teacher requests only.")

    if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        identity = request.session.get("authshield_keycloak_signup") or {}
        if (
            identity.get("role") != role
            or not identity.get("sub")
            or not identity.get("email")
            or identity.get("expires_at", 0) < timezone.now().timestamp()
        ):
            request.session.pop("authshield_keycloak_signup", None)
            return redirect(f"{reverse('keycloak_login')}?flow=register&role={role}")

        existing = User.objects.filter(email__iexact=identity["email"]).first()
        if existing and existing.approval_status != User.ApprovalStatus.REJECTED:
            request.session["authshield_registration_result"] = (
                "approved" if existing.is_active and existing.approval_status == User.ApprovalStatus.APPROVED
                else "pending" if existing.approval_status == User.ApprovalStatus.PENDING
                else "not_approved"
            )
            request.session.pop("authshield_keycloak_signup", None)
            return redirect("registration_status")

        form = KeycloakAccessRequestForm(
            request.POST or None,
            initial={"full_name": identity.get("full_name", "")},
        )
        if request.method == "POST":
            if not consume_public_request_quota(
                request,
                purpose="signup",
                limit=settings.AUTHSHIELD_SIGNUP_IP_LIMIT,
                window_minutes=settings.AUTHSHIELD_SIGNUP_IP_WINDOW_MINUTES,
            ):
                form.add_error(None, "Too many access requests came from this connection. Try again later.")
                return render(request, "accounts/signup.html", {
                    "form": form,
                    "role": role,
                    "role_label": role_label,
                    "keycloak_enabled": True,
                    "keycloak_email": identity["email"],
                }, status=429)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    existing = User.objects.select_for_update().filter(email__iexact=identity["email"]).first()
                    if existing:
                        if existing.keycloak_subject != identity["sub"] or existing.role != role:
                            raise IntegrityError("The existing request is linked to another account.")
                        existing.full_name = form.cleaned_data["full_name"].strip()
                        existing.phone_number = form.cleaned_data["phone_number"]
                        existing.is_active = False
                        existing.approval_status = User.ApprovalStatus.PENDING
                        existing.reviewed_at = None
                        existing.reviewed_by = None
                        existing.save(update_fields=(
                            "full_name", "phone_number", "is_active", "approval_status", "reviewed_at", "reviewed_by"
                        ))
                    else:
                        user = User(
                            email=identity["email"],
                            full_name=form.cleaned_data["full_name"].strip(),
                            phone_number=form.cleaned_data["phone_number"],
                            role=role,
                            approval_status=User.ApprovalStatus.PENDING,
                            is_active=False,
                            keycloak_subject=identity["sub"],
                        )
                        user.set_unusable_password()
                        user.save()
            except IntegrityError:
                form.add_error(None, "We could not link this sign-in to your request. Contact the portal administrator.")
            else:
                request.session.pop("authshield_keycloak_signup", None)
                messages.success(
                    request,
                    f"Your {role_label} access request was submitted. An administrator must approve it before you can sign in.",
                )
                return redirect("registration_status")

        return render(request, "accounts/signup.html", {
            "form": form,
            "role": role,
            "role_label": role_label,
            "keycloak_enabled": True,
            "keycloak_email": identity["email"],
        })

    form = form_class(request.POST or None)
    if request.method == "POST":
        if not consume_public_request_quota(
            request,
            purpose="signup",
            limit=settings.AUTHSHIELD_SIGNUP_IP_LIMIT,
            window_minutes=settings.AUTHSHIELD_SIGNUP_IP_WINDOW_MINUTES,
        ):
            form.add_error(None, "Too many access requests came from this connection. Try again later.")
            return render(request, "accounts/signup.html", {
                "form": form, "role": role, "role_label": role_label,
            }, status=429)

    if request.method == "POST" and form.is_valid():
        email = normalized_email(form.cleaned_data["email"])
        if not form.instance.pk and User.objects.filter(email__iexact=email).exists():
            messages.success(request, REGISTRATION_SUBMISSION_MESSAGE)
            return redirect("registration_status")

        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            if not form.instance.pk and User.objects.filter(email__iexact=email).exists():
                messages.success(request, REGISTRATION_SUBMISSION_MESSAGE)
                return redirect("registration_status")
            raise
        messages.success(request, REGISTRATION_SUBMISSION_MESSAGE)
        return redirect("registration_status")
    return render(request, "accounts/signup.html", {"form": form, "role": role, "role_label": role_label})


def signup_options(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "accounts/signup_options.html")


def _keycloak_identity_user(email, subject):
    """Resolve a local portal account by linked subject, or link a verified email once."""
    user = User.objects.filter(keycloak_subject=subject).first()
    if user:
        return (user, None) if normalized_email(user.email) == email else (None, "identity_mismatch")

    user = User.objects.filter(email__iexact=email).first()
    if not user:
        return None, None
    if user.keycloak_subject:
        return (user, None) if user.keycloak_subject == subject else (None, "identity_mismatch")

    try:
        user.keycloak_subject = subject
        user.save(update_fields=("keycloak_subject",))
    except IntegrityError:
        user.refresh_from_db()
        if user.keycloak_subject != subject:
            return None, "identity_mismatch"
    return user, None


@require_http_methods(["GET", "POST"])
def keycloak_login(request):
    if not settings.AUTHSHIELD_KEYCLOAK_ENABLED or not settings.AUTHSHIELD_LOGIN_ENABLED:
        return redirect("login")

    values = request.POST if request.method == "POST" else request.GET
    flow = values.get("flow", "login")
    role = values.get("role", "")
    if flow not in {"login", "register", "status"}:
        flow = "login"
    if flow == "register" and role not in {User.Role.STUDENT, User.Role.TEACHER}:
        messages.error(request, "Choose Student or Teacher access before registering.")
        return redirect("signup")

    request.session["authshield_keycloak_flow"] = flow
    request.session["authshield_keycloak_signup_role"] = role if flow == "register" else ""
    channel = values.get("otp_channel", values.get("channel", "email"))
    if channel not in {"sms", "email"}:
        channel = "email"
    if channel == "sms" and not firebase_phone_auth_available() and not settings.AUTHSHIELD_EMAIL_STEP_UP:
        channel = "email"
    request.session["authshield_keycloak_channel"] = channel
    requested_next = values.get("next", "")
    if requested_next and url_has_allowed_host_and_scheme(
        requested_next, {request.get_host()}, require_https=request.is_secure()
    ):
        request.session["authshield_keycloak_next"] = requested_next
    else:
        request.session.pop("authshield_keycloak_next", None)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)

    try:
        client = keycloak_client()
        prompt = "create" if flow == "register" else "login"
        return client.authorize_redirect(
            request,
            request.build_absolute_uri(reverse("keycloak_callback")),
            prompt=prompt,
        )
    except Exception as error:
        logger.warning("Could not start Keycloak sign-in (%s).", type(error).__name__)
        messages.error(request, "The identity service is unavailable. Try again later or contact the administrator.")
        return redirect("login")


def _finish_keycloak_sign_in(request, user, channel, next_url):
    mfa_policy = policy_for_user(user)
    if mfa_policy["enabled"]:
        channels = allowed_channels(user)
        if not channels:
            messages.error(request, "Required sign-in verification is not configured for this account. Contact the administrator.")
            return redirect("login")
        if mfa_policy["require_both"] and not delivery_target(user, "sms"):
            record_auth_event(
                "otp_delivery_failure", email=user.email,
                description="Required SMS verification is unavailable because the account has no valid phone number.",
                request=request, factor="mobile_otp", outcome="failure",
            )
            messages.error(request, "Your account needs a valid mobile number for required SMS verification. Contact the administrator.")
            return redirect("login")
        channel = initial_channel(user, channel)

        if channel == "sms":
            try:
                _prepare_firebase_sms_challenge(request, user)
            except (OTPProviderError, ImproperlyConfigured):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Firebase SMS sign-in could not be prepared after Keycloak authentication.",
                    request=request, factor="mobile_otp", outcome="failure",
                )
                messages.error(request, "We could not start SMS verification. Try email verification or contact the administrator.")
                return redirect("login")
        else:
            try:
                _start_otp(request, user, "email")
            except OTPDeliveryRateLimited as error:
                messages.error(request, f"Email code sending is paused. You can request another in {_otp_wait_label(error.available_at)}.")
                return redirect("login")
            except (OTPProviderError, ImproperlyConfigured):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Email OTP could not be started after Keycloak authentication.",
                    request=request, factor="email_otp", outcome="failure",
                )
                messages.error(request, "We could not send a verification code. Try again or contact the administrator.")
                return redirect("login")
            record_auth_event(
                "otp_sent", email=user.email,
                description="A sign-in verification code was requested after Keycloak authentication.",
                request=request, factor="email_otp", outcome="success",
            )

        if next_url and url_has_allowed_host_and_scheme(
            next_url, {request.get_host()}, require_https=request.is_secure()
        ):
            request.session["authshield_otp_next"] = next_url
        return redirect("otp_verify")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    clear_expired_or_successful_lock(user)
    record_auth_event(
        "login_success",
        email=user.email,
        actor=user,
        description="Successful Keycloak sign-in without an additional portal OTP.",
        request=request,
        factor="password",
        outcome="success",
        auth_mode="keycloak",
    )
    if user.must_change_password:
        return redirect("password_change")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, {request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(settings.LOGIN_REDIRECT_URL)


@require_http_methods(["GET"])
def keycloak_callback(request):
    if not settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        return redirect("login")

    try:
        token = keycloak_client().authorize_access_token(request)
        claims = token.get("userinfo") or {}
    except Exception as error:
        logger.warning("Keycloak callback failed (%s).", type(error).__name__)
        for key in (
            "authshield_keycloak_flow", "authshield_keycloak_signup_role",
            "authshield_keycloak_channel", "authshield_keycloak_next",
        ):
            request.session.pop(key, None)
        messages.error(request, "Keycloak could not verify this sign-in. Start again.")
        return redirect("login")

    email = normalized_email(claims.get("email", ""))
    subject = claims.get("sub", "")
    if not email or not subject or claims.get("email_verified") is not True:
        messages.error(request, "Verify your email in Keycloak before using this school portal account.")
        return redirect("login")

    flow = request.session.pop("authshield_keycloak_flow", "login")
    role = request.session.pop("authshield_keycloak_signup_role", "")
    channel = request.session.pop("authshield_keycloak_channel", "sms")
    next_url = request.session.pop("authshield_keycloak_next", "")

    if flow == "register":
        user, issue = _keycloak_identity_user(email, subject)
        if issue:
            messages.error(request, "This identity is already linked to another portal account. Contact the administrator.")
            return redirect("login")
        if user:
            if user.role not in (User.Role.STUDENT, User.Role.TEACHER):
                messages.error(request, "This account cannot submit a Student or Teacher access request.")
                return redirect("login")
            if user.approval_status != User.ApprovalStatus.REJECTED:
                request.session["authshield_registration_result"] = (
                    "approved" if user.is_active and user.approval_status == User.ApprovalStatus.APPROVED
                    else "pending" if user.approval_status == User.ApprovalStatus.PENDING
                    else "not_approved"
                )
                return redirect("registration_status")
        if role not in (User.Role.STUDENT, User.Role.TEACHER):
            messages.error(request, "Choose Student or Teacher access before registering.")
            return redirect("signup")
        request.session["authshield_keycloak_signup"] = {
            "sub": subject,
            "email": email,
            "full_name": str(claims.get("name") or "").strip()[:150],
            "role": role,
            "expires_at": timezone.now().timestamp() + 600,
        }
        return redirect("student_signup" if role == User.Role.STUDENT else "teacher_signup")

    user, issue = _keycloak_identity_user(email, subject)
    if flow == "status":
        if user and user.role in (User.Role.STUDENT, User.Role.TEACHER):
            request.session["authshield_registration_result"] = (
                "approved" if user.is_active and user.approval_status == User.ApprovalStatus.APPROVED
                else "pending" if user.approval_status == User.ApprovalStatus.PENDING
                else "not_approved"
            )
        else:
            request.session["authshield_registration_error"] = True
        return redirect("registration_status")

    if issue or not user:
        messages.error(request, "No matching portal account is linked to this Keycloak identity. Request Student or Teacher access first.")
        return redirect("login")
    if flow == "update_password":
        expected_user_id = request.session.pop("authshield_keycloak_password_user_id", None)
        if request.GET.get("kc_action_status") == "cancelled":
            messages.info(request, "Password change was cancelled. Your current password remains active.")
            return redirect("password_change")
        if (
            not expected_user_id
            or user.pk != expected_user_id
            or request.GET.get("kc_action_status") != "success"
        ):
            messages.error(request, "Keycloak did not confirm the password change. Start the change again.")
            return redirect("password_change")
        user.must_change_password = False
        user.save(update_fields=("must_change_password",))
        record_auth_event(
            "password_reset_completed", email=user.email, actor=user,
            description="The account holder completed a required password change in Keycloak.",
            request=request, factor="password", outcome="success",
        )
        messages.success(request, "Your Keycloak password has been changed.")
        return redirect("dashboard")
    if not user.is_active or user.approval_status != User.ApprovalStatus.APPROVED:
        messages.info(request, "This account is waiting for administrator approval. Check your access-request status.")
        return redirect("registration_status")
    if user.locked_until and user.locked_until > timezone.now():
        record_blocked_attempt(user.email, request, action="locked_out")
        messages.error(request, f"This account is temporarily locked. Try again in {retry_minutes(user.locked_until)} minutes.")
        return redirect("login")

    request.session["authshield_keycloak_id_token"] = str(token.get("id_token") or "")
    return _finish_keycloak_sign_in(request, user, channel, next_url)


def registration_status(request):
    if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        if request.method == "POST":
            return redirect(f"{reverse('keycloak_login')}?flow=status")
        return render(request, "accounts/registration_status.html", {
            "keycloak_enabled": True,
            "result": request.session.pop("authshield_registration_result", None),
            "status_error": request.session.pop("authshield_registration_error", False),
            "form": None,
        })

    form = RegistrationStatusForm(request.POST or None)
    result = None
    started_at = time.monotonic()
    if request.method == "POST":
        email = normalized_email(request.POST.get("email", ""))
        password = request.POST.get("password", "")
        duration_ms = int((time.monotonic() - started_at) * 1000)
        now = timezone.now()
        account_until = account_lockout_until(email, now)
        source_until = ip_throttle_until(request, now)
        if account_until or source_until:
            until = account_until or source_until
            record_blocked_attempt(
                email,
                request,
                action="locked_out" if account_until else "ip_rate_limited",
                duration_ms=duration_ms,
            )
            form.add_error(None, f"Too many attempts. Try again in {retry_minutes(until, now)} minutes.")
        elif form.is_valid():
            user = User.objects.filter(email__iexact=email).first()
            if user and user.check_password(password) and user.role in (User.Role.STUDENT, User.Role.TEACHER):
                clear_expired_or_successful_lock(user)
                record_auth_event(
                    "registration_status_success",
                    email=email,
                    actor=user,
                    description="Successful account-request status check.",
                    request=request,
                    factor="password",
                    outcome="success",
                    duration_ms=duration_ms,
                )
                if user.approval_status == User.ApprovalStatus.PENDING:
                    result = "pending"
                elif user.approval_status == User.ApprovalStatus.APPROVED and user.is_active:
                    result = "approved"
                else:
                    result = "not_approved"
            else:
                record_failed_authentication(
                    email,
                    "registration_status_failure",
                    request,
                    duration_ms=duration_ms,
                )
                form.add_error(None, "We could not check this request. Verify the details and try again.")
        elif email or password:
            record_failed_authentication(
                email,
                "registration_status_failure",
                request,
                duration_ms=duration_ms,
            )
            form.add_error(None, "We could not check this request. Verify the details and try again.")
    return render(
        request,
        "accounts/registration_status.html",
        {
            "form": form,
            "result": result,
            "keycloak_enabled": settings.AUTHSHIELD_KEYCLOAK_ENABLED and settings.AUTHSHIELD_LOGIN_ENABLED,
        },
    )


class BaselineLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        self._auth_started_at = time.monotonic()
        if not settings.AUTHSHIELD_LOGIN_ENABLED:
            raise PermissionDenied("Sign-in is disabled until the authentication stage is configured.")
        if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
            if request.user.is_authenticated:
                return redirect("dashboard")
            if request.method != "GET":
                return redirect("keycloak_login")
            return render(request, self.template_name, {
                "keycloak_enabled": True,
                "otp_enabled": True,
                "email_step_up": settings.AUTHSHIELD_EMAIL_STEP_UP,
                "mobile_otp_enabled": firebase_phone_auth_available(),
                "next": request.GET.get("next", ""),
            })
        return super().dispatch(request, *args, **kwargs)

    def _duration_ms(self):
        return max(0, int((time.monotonic() - self._auth_started_at) * 1000))

    def form_valid(self, form):
        user = form.get_user()
        mfa_policy = policy_for_user(user)
        account_requires_otp = mfa_policy["enabled"]
        if account_requires_otp:
            if mfa_policy["require_both"] and not delivery_target(user, "sms"):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Required SMS verification is unavailable because the account has no valid phone number.",
                    request=self.request, factor="mobile_otp", outcome="failure",
                )
                form.add_error(None, "Your account needs a valid mobile number for required SMS verification. Contact the administrator.")
                return self.render_to_response(self.get_context_data(form=form))
            channel = initial_channel(user, form.cleaned_data.get("otp_channel") or "email")
            if not channel:
                form.add_error(None, "Required sign-in verification is not configured for this account. Contact the administrator.")
                return self.render_to_response(self.get_context_data(form=form))
            if channel == "sms":
                if not firebase_phone_auth_available():
                    record_auth_event(
                        "otp_delivery_failure", email=user.email,
                        description="Firebase SMS sign-in is not configured.",
                        request=self.request, factor="mobile_otp", outcome="failure",
                    )
                    form.add_error(None, "SMS sign-in is not configured yet. Choose Email or contact the administrator.")
                    return self.render_to_response(self.get_context_data(form=form))
                if not delivery_target(user, "sms"):
                    form.add_error(None, "This account needs a valid international mobile number for SMS. Choose Email or ask an administrator to update it.")
                    return self.render_to_response(self.get_context_data(form=form))
                try:
                    _prepare_firebase_sms_challenge(self.request, user)
                except (OTPProviderError, ImproperlyConfigured) as error:
                    record_auth_event(
                        "otp_delivery_failure", email=user.email,
                        description="Firebase SMS sign-in could not be started.",
                        request=self.request, factor="mobile_otp", outcome="failure",
                    )
                    if isinstance(error, ImproperlyConfigured):
                        form.add_error(None, "SMS sign-in is not configured yet. Choose Email or contact the administrator.")
                    else:
                        form.add_error(None, "This account needs a valid international phone number for SMS. Choose Email or ask an administrator to update it.")
                    return self.render_to_response(self.get_context_data(form=form))
            else:
                try:
                    _start_otp(self.request, user, channel)
                except OTPDeliveryRateLimited as error:
                    self.otp_delivery_wait_until = error.available_at.timestamp()
                    form.add_error(
                        None,
                        f"Code sending is paused. You can request another in {_otp_wait_label(error.available_at)}.",
                    )
                    return self.render_to_response(self.get_context_data(form=form))
                except (OTPProviderError, ImproperlyConfigured):
                    record_auth_event(
                        "otp_delivery_failure", email=user.email,
                        description="The configured email one-time-code service could not start a challenge.",
                        request=self.request, factor="email_otp", outcome="failure",
                    )
                    form.add_error(None, "We could not send a verification code. Try again or choose another method.")
                    return self.render_to_response(self.get_context_data(form=form))
            next_url = self.get_redirect_url()
            if next_url and url_has_allowed_host_and_scheme(next_url, {self.request.get_host()}, require_https=self.request.is_secure()):
                self.request.session["authshield_otp_next"] = next_url
            if channel == "email":
                record_auth_event(
                    "otp_sent", email=user.email,
                    description="A sign-in verification code was requested.",
                    request=self.request, factor="email_otp", outcome="success",
                )
            return redirect("otp_verify")

        response = super().form_valid(form)
        clear_expired_or_successful_lock(user)
        record_auth_event(
            "login_success",
            email=user.email,
            actor=user,
            description="Successful password-only sign-in.",
            request=self.request,
            factor="password",
            outcome="success",
            auth_mode="password",
            duration_ms=self._duration_ms(),
        )
        if user.must_change_password:
            return redirect("password_change")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["otp_enabled"] = True
        context["email_step_up"] = settings.AUTHSHIELD_EMAIL_STEP_UP
        context["keycloak_enabled"] = settings.AUTHSHIELD_KEYCLOAK_ENABLED
        context["mobile_otp_enabled"] = firebase_phone_auth_available()
        context["lockout_until"] = 0
        context["otp_delivery_wait_until"] = getattr(self, "otp_delivery_wait_until", 0)
        if self.request.method == "POST":
            email = normalized_email(self.request.POST.get("username", ""))
            now = timezone.now()
            account_until = account_lockout_until(email, now)
            source_until = ip_throttle_until(self.request, now, email=email, exempt_admin=True)
            until = account_until or source_until
            if until:
                context["lockout_until"] = until.timestamp()
                remaining = max(0, int((until - now).total_seconds() + 0.999))
                context["lockout_clock_initial"] = f"{remaining // 60:02d}:{remaining % 60:02d}"
                context["lockout_message"] = (
                    f"This account is temporarily locked after {settings.AUTHSHIELD_LOCKOUT_ATTEMPTS} failed attempts."
                    if account_until
                    else "Sign-in is temporarily limited from this network after repeated requests."
                )
        return context

    def form_invalid(self, form):
        email = normalized_email(self.request.POST.get("username", ""))
        duration_ms = self._duration_ms()
        if form.has_error(NON_FIELD_ERRORS, "account_locked"):
            record_blocked_attempt(email, self.request, action="locked_out", duration_ms=duration_ms)
        elif form.has_error(NON_FIELD_ERRORS, "ip_rate_limited"):
            record_blocked_attempt(email, self.request, action="ip_rate_limited", duration_ms=duration_ms)
        elif form.cleaned_data.get("username") and form.cleaned_data.get("password"):
            record_failed_authentication(
                email,
                "login_failure",
                self.request,
                duration_ms=duration_ms,
            )
        return super().form_invalid(form)


@require_http_methods(["GET", "POST"])
def otp_verify(request):
    user_id = request.session.get("authshield_otp_user_id")
    if not user_id:
        _clear_otp_session(request)
        messages.info(request, "Start sign-in again to request a verification code.")
        return redirect("login")
    user = User.objects.filter(pk=user_id, is_active=True, approval_status=User.ApprovalStatus.APPROVED).first()
    if not user or (user.role != User.Role.ADMIN and user.locked_until and user.locked_until > timezone.now()):
        _clear_otp_session(request)
        messages.error(request, "Sign-in could not continue. Start again or contact the administrator.")
        return redirect("login")

    channel = request.session.get("authshield_otp_channel", "")
    phase = request.session.get("authshield_otp_phase", "primary")
    if not _otp_policy_is_current(request, user):
        _clear_otp_session(request)
        messages.info(request, "MFA settings changed during sign-in. Start again to use the current verification method.")
        return redirect("login")
    if not channel_is_allowed(user, channel, phase=phase):
        _clear_otp_session(request)
        messages.info(request, "The sign-in verification policy changed. Start sign-in again.")
        return redirect("login")
    if phase == "primary" and policy_for_user(user)["require_both"] and channel != "sms":
        _clear_otp_session(request)
        messages.info(request, "The sign-in policy requires SMS verification first. Start sign-in again.")
        return redirect("login")
    if channel == "email":
        challenge_replaced, challenge_completed = _sync_email_otp_challenge(request, user, phase)
        if challenge_completed:
            _clear_otp_session(request)
            messages.info(request, "That sign-in code has already been used. Start sign-in again for a new code.")
            return redirect("login")
        if challenge_replaced:
            messages.info(request, "A newer code replaced the one on this page. Use the newest AuthShield email.")
            if request.method == "POST":
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))
    if timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        if not request.session.get("authshield_otp_expiry_logged"):
            record_auth_event(
                "otp_expired",
                email=user.email,
                description="The sign-in code expired before verification completed.",
                request=request,
                factor="email_otp" if channel == "email" else "mobile_otp",
                outcome="failure",
                duration_ms=_otp_duration_ms(request),
            )
            request.session["authshield_otp_expiry_logged"] = True
        if request.method == "POST":
            messages.error(request, "That code has expired. Request a new code to continue.")
        return render(
            request,
            "accounts/otp_verify.html",
            _otp_context(request, user, channel, phase),
            status=400 if request.method == "POST" else 200,
        )
    if request.method == "POST":
        now = timezone.now()
        source_until = ip_throttle_until(request, now, email=user.email, exempt_admin=True)
        if source_until:
            record_blocked_attempt(user.email, request, action="ip_rate_limited")
            messages.error(request, f"Too many attempts. Try again in {retry_minutes(source_until, now)} minutes.")
            return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=429)
        code = (request.POST.get("code") or "").strip()
        attempts = request.session.get("authshield_otp_attempts", 0)
        purpose = "email_step_up" if phase == "email_step_up" else "sign_in"
        if attempts >= MAX_OTP_ATTEMPTS:
            request.session["authshield_otp_expires_at"] = now.timestamp()
            messages.error(request, "Too many incorrect codes. Request a new code to continue.")
            return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))
        if channel == "email":
            challenge = EmailOTPChallenge.objects.filter(user=user, purpose=purpose).only("attempts", "code_hash").first()
            if challenge and (challenge.attempts >= MAX_OTP_ATTEMPTS or not challenge.code_hash):
                request.session["authshield_otp_expires_at"] = now.timestamp()
                messages.error(request, "This code has reached its attempt limit. Request a new code to continue.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))
        if channel == "sms":
            if not request.session.get("authshield_otp_sms_sent"):
                messages.error(request, "Request the SMS code first, then enter it here.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=400)
            try:
                verified_token = verify_firebase_phone_id_token(
                    request.POST.get("firebase_id_token", ""),
                    expected_phone=delivery_target(user, "sms"),
                    minimum_auth_time=request.session.get("authshield_otp_started_at", 0),
                )
                approved = verified_token is not None
            except (OTPProviderError, ImproperlyConfigured):
                messages.error(request, "Firebase could not verify the sign-in right now. Try again shortly.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=503)
        else:
            try:
                approved = check_otp(
                    delivery_target(user, channel),
                    channel,
                    code,
                    request.session,
                    user=user,
                    purpose=purpose,
                    expected_sent_at=request.session.get("authshield_otp_sent_at"),
                )
            except OTPChallengeChanged:
                challenge_replaced, challenge_completed = _sync_email_otp_challenge(request, user, phase)
                if challenge_completed:
                    _clear_otp_session(request)
                    messages.info(request, "That sign-in code has already been used. Start sign-in again for a new code.")
                    return redirect("login")
                if challenge_replaced:
                    messages.info(request, "A newer code replaced the one on this page. Use the newest AuthShield email.")
                else:
                    request.session["authshield_otp_expires_at"] = timezone.now().timestamp()
                    messages.error(request, "This code is no longer active. Request a new code or restart sign-in.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))
            except OTPChallengeExpired:
                if not request.session.get("authshield_otp_expiry_logged"):
                    record_auth_event(
                        "otp_expired",
                        email=user.email,
                        description="The sign-in code expired while verification was in progress.",
                        request=request,
                        factor="email_otp",
                        outcome="failure",
                        duration_ms=_otp_duration_ms(request),
                    )
                    request.session["authshield_otp_expiry_logged"] = True
                request.session["authshield_otp_expires_at"] = timezone.now().timestamp()
                messages.error(request, "That code has expired. Request a new code to continue.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=400)
            except (OTPProviderError, ImproperlyConfigured):
                messages.error(request, "We could not verify that code right now. Try again shortly.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=503)
        if not approved:
            attempts += 1
            request.session["authshield_otp_attempts"] = attempts
            record_failed_authentication(
                user.email,
                "otp_failure",
                request,
                factor="email_otp" if channel == "email" else "mobile_otp",
                duration_ms=_otp_duration_ms(request),
                description="An invalid or expired one-time code was submitted.",
            )
            sms_allowed, sms_attempts = (True, 0)
            if channel == "sms":
                sms_allowed, sms_attempts = _record_sms_otp_failure(user)
            user.refresh_from_db(fields=["locked_until"])
            if user.role != User.Role.ADMIN and user.locked_until and user.locked_until > timezone.now():
                _clear_otp_session(request)
                messages.error(request, "Too many attempts. The account is temporarily locked.")
                return redirect("login")
            challenge_exhausted = False
            if channel == "email":
                challenge = EmailOTPChallenge.objects.filter(user=user, purpose=purpose).only("attempts", "code_hash").first()
                challenge_exhausted = bool(
                    challenge and (challenge.attempts >= MAX_OTP_ATTEMPTS or not challenge.code_hash)
                )
            if not sms_allowed or sms_attempts >= MAX_OTP_ATTEMPTS:
                _clear_otp_session(request)
                messages.error(request, "Too many incorrect SMS codes. Restart sign-in later.")
                return redirect("login")
            if attempts >= MAX_OTP_ATTEMPTS or challenge_exhausted:
                request.session["authshield_otp_expires_at"] = timezone.now().timestamp()
                messages.error(request, "Too many incorrect codes. Request a new code to continue.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))
            messages.error(request, "That code is invalid or expired. Check it and try again.")
            return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))

        record_auth_event(
            "otp_success",
            email=user.email,
            description="A sign-in one-time code was verified successfully.",
            request=request,
            factor="email_otp" if channel == "email" else "mobile_otp",
            outcome="success",
            auth_mode="otp_email" if phase == "email_step_up" else "otp",
            duration_ms=_otp_duration_ms(request),
        )

        if phase == "primary" and policy_for_user(user)["require_both"] and channel == "sms":
            try:
                _start_otp(request, user, "email", phase="email_step_up")
            except OTPDeliveryRateLimited as error:
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Email step-up verification was rate limited after SMS verification.",
                    request=request, factor="email_otp", outcome="failure",
                )
                _clear_otp_session(request)
                messages.error(
                    request,
                    f"Email code sending is paused. Wait { _otp_wait_label(error.available_at) } and start sign-in again.",
                )
                return redirect("login")
            except (OTPProviderError, ImproperlyConfigured):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Email step-up verification could not be started after SMS verification.",
                    request=request, factor="email_otp", outcome="failure",
                )
                messages.error(request, "Email verification could not be started. Sign-in has not completed.")
                _clear_otp_session(request)
                return redirect("login")
            record_auth_event(
                "otp_sent",
                email=user.email,
                description="An email sign-in code was requested after SMS verification.",
                request=request,
                factor="email_otp",
                outcome="success",
            )
            messages.success(request, "SMS verified. Enter the email code to finish signing in.")
            return redirect("otp_verify")

        keycloak_primary = bool(request.session.get("authshield_keycloak_id_token"))
        completed_both = phase in {"sms_step_up", "email_step_up"}
        auth_mode = "keycloak_otp_email" if keycloak_primary and completed_both else (
            "keycloak_otp" if keycloak_primary else ("otp_email" if completed_both else "otp")
        )
        duration_ms = _otp_duration_ms(request)
        next_url = request.session.get("authshield_otp_next") or settings.LOGIN_REDIRECT_URL
        _clear_otp_session(request)
        clear_expired_or_successful_lock(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.pop("authshield_keycloak_login", None)
        record_auth_event(
            "login_success",
            email=user.email,
            actor=user,
            description=(
                "Successful Keycloak password and one-time-code sign-in."
                if keycloak_primary else "Successful password and one-time-code sign-in."
            ),
            request=request,
            factor="email_otp" if channel == "email" else "mobile_otp",
            outcome="success",
            auth_mode=auth_mode,
            duration_ms=duration_ms,
        )
        if user.must_change_password:
            return redirect("password_change")
        return redirect(next_url)

    return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase))


def _pending_sms_user(request, *, allow_expired=False):
    user_id = request.session.get("authshield_otp_user_id")
    if (
        request.session.get("authshield_otp_channel") != "sms"
        or not firebase_phone_auth_available()
    ):
        return None
    user = User.objects.filter(
        pk=user_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    ).first()
    if not user or (user.role != User.Role.ADMIN and user.locked_until and user.locked_until > timezone.now()):
        return None
    if not _otp_policy_is_current(request, user):
        return None
    if not channel_is_allowed(
        user,
        "sms",
        phase=request.session.get("authshield_otp_phase", "primary"),
    ):
        return None
    if not allow_expired and timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        return None
    if not delivery_target(user, "sms"):
        return None
    return user


def _record_sms_otp_failure(user):
    """Count invalid SMS codes persistently across browser sessions."""
    now = timezone.now()
    window = timedelta(minutes=settings.AUTHSHIELD_SMS_OTP_ACCOUNT_WINDOW_MINUTES)
    with transaction.atomic():
        limit, _ = SMSOTPDeliveryLimit.objects.get_or_create(
            user=user,
            defaults={"window_started_at": now},
        )
        limit = SMSOTPDeliveryLimit.objects.select_for_update().get(pk=limit.pk)
        if now - limit.window_started_at >= window:
            limit.window_started_at = now
            limit.request_count = 0
            limit.verification_attempts = 0
            limit.last_requested_at = None
        if limit.verification_attempts >= MAX_OTP_ATTEMPTS:
            return False, limit.verification_attempts
        limit.verification_attempts += 1
        limit.save(update_fields=("window_started_at", "last_requested_at", "request_count", "verification_attempts"))
        return True, limit.verification_attempts


@require_POST
def otp_sms_authorize_send(request):
    user = _pending_sms_user(request, allow_expired=True)
    if not user:
        return JsonResponse({"error": "Restart sign-in before requesting an SMS code."}, status=400)
    sms_failures = SMSOTPDeliveryLimit.objects.filter(user=user).values_list("verification_attempts", flat=True).first() or 0
    if sms_failures >= MAX_OTP_ATTEMPTS:
        return JsonResponse({"error": "Too many incorrect SMS codes were entered for this account. Try again later."}, status=429)
    now_dt = timezone.now()
    allowed, available_at = _reserve_otp_delivery(user, "sms", now_dt)
    if not allowed:
        remaining = _otp_wait_label(available_at, now_dt)
        message = (
            f"SMS sending is paused. Try again in {remaining}."
            if available_at > now_dt + timedelta(seconds=settings.AUTHSHIELD_OTP_RESEND_COOLDOWN_SECONDS)
            else f"Wait {remaining} before requesting another SMS code."
        )
        return JsonResponse({
            "error": message,
            "nextAvailableAt": available_at.timestamp(),
        }, status=429, headers={"Retry-After": str(max(1, ceil((available_at - now_dt).total_seconds())))})
    now = now_dt.timestamp()
    request.session["authshield_otp_sms_sent_at"] = now
    request.session["authshield_otp_sms_send_authorized_at"] = now
    request.session["authshield_otp_sms_sent"] = False
    request.session.save()
    return JsonResponse({"ok": True, "nextAvailableAt": available_at.timestamp()})


@require_POST
def otp_sms_mark_sent(request):
    user = _pending_sms_user(request, allow_expired=True)
    authorized_at = request.session.get("authshield_otp_sms_send_authorized_at", 0)
    if not user or not authorized_at or timezone.now().timestamp() - authorized_at > 120:
        return JsonResponse({"error": "The SMS request expired. Request a new code."}, status=400)
    request.session["authshield_otp_sms_sent"] = True
    now = timezone.now().timestamp()
    request.session["authshield_otp_sent_at"] = now
    request.session["authshield_otp_started_at"] = now
    request.session["authshield_otp_expires_at"] = now + settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    request.session.pop("authshield_otp_expiry_logged", None)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    request.session.save()
    record_auth_event(
        "otp_sent", email=user.email,
        description="The browser reported Firebase accepted the SMS request; phone-code verification is still required.",
        request=request, factor="mobile_otp", outcome="success",
    )
    next_available_at = _otp_delivery_available_at(user, "sms")
    return JsonResponse({
        "ok": True,
        "sentAt": now,
        "expiresAt": request.session["authshield_otp_expires_at"],
        "resendAvailableAt": next_available_at.timestamp(),
    })


@require_POST
def otp_sms_record_failure(request):
    user = _pending_sms_user(request, allow_expired=True)
    if not user or not request.session.get("authshield_otp_sms_sent"):
        return JsonResponse({"error": "The SMS sign-in has expired. Restart sign-in."}, status=400)
    attempts = request.session.get("authshield_otp_attempts", 0) + 1
    request.session["authshield_otp_attempts"] = attempts
    record_failed_authentication(
        user.email,
        "otp_failure",
        request,
        factor="mobile_otp",
        duration_ms=_otp_duration_ms(request),
        description="Firebase rejected an SMS verification code.",
    )
    allowed, account_attempts = _record_sms_otp_failure(user)
    user.refresh_from_db(fields=["locked_until"])
    if not allowed or (user.role != User.Role.ADMIN and user.locked_until and user.locked_until > timezone.now()) or attempts >= MAX_OTP_ATTEMPTS or account_attempts >= MAX_OTP_ATTEMPTS:
        _clear_otp_session(request)
        messages.error(request, "Too many incorrect SMS codes. Restart sign-in to request a new code.")
        return JsonResponse({"error": "Too many code attempts. Restart sign-in later."}, status=429)
    request.session.save()
    return JsonResponse({"ok": True, "remainingAttempts": max(0, MAX_OTP_ATTEMPTS - account_attempts)})


@require_http_methods(["POST"])
def otp_resend(request):
    user_id = request.session.get("authshield_otp_user_id")
    user = User.objects.filter(pk=user_id, is_active=True, approval_status=User.ApprovalStatus.APPROVED).first()
    channel = request.session.get("authshield_otp_channel", "")
    phase = request.session.get("authshield_otp_phase", "primary")
    if (
        not user
        or not _otp_policy_is_current(request, user)
        or channel != "email"
        or not channel_is_allowed(user, channel, phase=phase)
    ):
        _clear_otp_session(request)
        messages.error(request, "Start sign-in again to request a verification code.")
        return redirect("login")
    try:
        challenge = _start_otp(request, user, channel, phase=phase, reset_resends=False, force_new=True)
    except OTPDeliveryRateLimited as error:
        messages.error(request, f"Code sending is paused. You can request another in {_otp_wait_label(error.available_at)}.")
        return redirect("otp_verify")
    except (OTPProviderError, ImproperlyConfigured):
        messages.error(request, "We could not send another code right now.")
        return redirect("otp_verify")
    if challenge and not getattr(challenge, "_email_sent", True):
        messages.info(request, "A code was just sent. Check that message, then wait before requesting another.")
        return redirect("otp_verify")
    record_auth_event(
        "otp_sent", email=user.email,
        description="A replacement sign-in verification code was requested.",
        request=request,
        factor="email_otp",
        outcome="success",
    )
    request.session["authshield_otp_resends"] = request.session.get("authshield_otp_resends", 0) + 1
    messages.success(request, "A new verification code was sent.")
    return redirect("otp_verify")


def _clear_password_reset_session(request):
    request.session.pop("authshield_password_reset_user_id", None)
    request.session.pop("authshield_password_reset_resends", None)
    request.session.pop("authshield_password_reset_expires_at", None)
    request.session.pop("authshield_password_reset_sent_at", None)
    request.session.pop("authshield_password_reset_started_at", None)


def _password_reset_user(**lookup):
    eligible_users = User.objects.filter(
        Q(is_active=True, approval_status=User.ApprovalStatus.APPROVED)
        | Q(
            role__in=(User.Role.STUDENT, User.Role.TEACHER),
            approval_status=User.ApprovalStatus.PENDING,
        )
    )
    return eligible_users.filter(**lookup).first()


def _password_reset_account_send_allowed(user, now=None):
    """Limit reset emails per account across browser sessions and app instances."""
    return consume_throttle_quota(
        scope="password-reset-account",
        purpose="password-reset-account",
        identity=str(user.pk),
        limit=settings.AUTHSHIELD_PASSWORD_RESET_ACCOUNT_LIMIT,
        window_minutes=settings.AUTHSHIELD_PASSWORD_RESET_ACCOUNT_WINDOW_MINUTES,
        now=now,
    )


def _password_reset_request_allowed(request, now=None):
    """Apply a cross-instance IP limit without storing the visitor's raw IP."""
    address = request_ip(request)
    if not address:
        return True

    now = now or timezone.now()
    fingerprint = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"password-reset-ip:{address}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    window = timedelta(minutes=settings.AUTHSHIELD_PASSWORD_RESET_IP_WINDOW_MINUTES)
    with transaction.atomic():
        bucket, _ = PasswordResetRequestLimit.objects.select_for_update().get_or_create(
            fingerprint=fingerprint,
            defaults={"window_started_at": now},
        )
        if now - bucket.window_started_at >= window:
            bucket.window_started_at = now
            bucket.request_count = 0
        if bucket.request_count >= settings.AUTHSHIELD_PASSWORD_RESET_IP_LIMIT:
            return False
        bucket.request_count += 1
        bucket.save(update_fields=("window_started_at", "request_count"))

    # Keep abandoned IP buckets from accumulating indefinitely.
    PasswordResetRequestLimit.objects.filter(window_started_at__lt=now - timedelta(days=2)).delete()
    return True


def _wait_for_password_reset_response(started_at):
    floor = settings.AUTHSHIELD_PASSWORD_RESET_RESPONSE_FLOOR_SECONDS
    remaining = floor - (time.monotonic() - started_at)
    if remaining > 0:
        time.sleep(remaining)


@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        messages.info(request, "Use ‘Forgot password?’ on the Keycloak sign-in page to reset your password.")
        return redirect("keycloak_login")

    response_started_at = time.monotonic()
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _clear_otp_session(request)
        _clear_password_reset_session(request)
        now_datetime = timezone.now()
        now = now_datetime.timestamp()
        request.session["authshield_password_reset_started_at"] = now
        request.session["authshield_password_reset_sent_at"] = now
        request.session["authshield_password_reset_resends"] = 0
        request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        email = normalized_email(form.cleaned_data["email"])
        if not _password_reset_request_allowed(request, now_datetime):
            _wait_for_password_reset_response(response_started_at)
            return redirect("password_reset_verify")
        user = _password_reset_user(email__iexact=email)
        if user:
            prior_challenge = EmailOTPChallenge.objects.filter(
                user=user,
                purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
            ).first()
            cooldown_active = bool(
                prior_challenge
                and prior_challenge.sent_at
                and (now_datetime - prior_challenge.sent_at).total_seconds()
                < settings.AUTHSHIELD_PASSWORD_RESET_OTP_TTL_SECONDS
            )
            # Keep the eligible account in this browser session so a transient
            # mail-delivery failure can be retried from the same generic page.
            request.session["authshield_password_reset_user_id"] = user.pk
            email_was_sent = False
            try:
                if not cooldown_active and _password_reset_account_send_allowed(user, now_datetime):
                    challenge = start_otp(
                        user.email,
                        "email",
                        request.session,
                        recipient_name=user.full_name,
                        user=user,
                        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
                    )
                    email_was_sent = bool(getattr(challenge, "_email_sent", False))
            except OTPProviderError:
                record_auth_event(
                    "password_reset_otp_failure",
                    email=user.email,
                    actor=user,
                    description="Email delivery for a password recovery code could not be completed.",
                    request=request,
                    factor="email_otp",
                    outcome="failure",
                )
            except ImproperlyConfigured:
                # Without the challenge table or provider configuration there
                # is no recoverable reset request to associate with this page.
                request.session.pop("authshield_password_reset_user_id", None)
                record_auth_event(
                    "password_reset_otp_failure",
                    email=user.email,
                    actor=user,
                    description="Email password recovery is not configured for this deployment.",
                    request=request,
                    factor="email_otp",
                    outcome="failure",
                )
            else:
                request.session["authshield_password_reset_user_id"] = user.pk
                request.session.set_expiry(settings.SESSION_COOKIE_AGE)
                if email_was_sent:
                    record_auth_event(
                        "password_reset_otp_sent",
                        email=user.email,
                        actor=user,
                        description="A password recovery code was sent.",
                        request=request,
                        factor="email_otp",
                        outcome="success",
                    )
        # Keep the response the same for known and unknown addresses.
        _wait_for_password_reset_response(response_started_at)
        return redirect("password_reset_verify")
    return render(request, "accounts/password_reset_request.html", {"form": form})


@require_http_methods(["GET", "POST"])
def password_reset_verify(request):
    user_id = request.session.get("authshield_password_reset_user_id")
    user = _password_reset_user(pk=user_id) if user_id else None
    challenge = EmailOTPChallenge.objects.filter(
        user=user,
        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
    ).first() if user else None
    has_reset_request = bool(request.session.get("authshield_password_reset_started_at"))
    password_form = SetPasswordForm(user, request.POST or None) if has_reset_request else None
    if password_form:
        password_form.fields["new_password1"].widget.attrs["placeholder"] = "Create a new password"
        password_form.fields["new_password2"].widget.attrs["placeholder"] = "Enter your new password again"
    now = timezone.now()
    active = bool(
        challenge
        and challenge.code_hash
        and challenge.expires_at
        and challenge.expires_at > now
        and not challenge.completed_at
    )
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        failure_message = "That code is invalid or expired. Check your email and try again."
        failed_code = False
        completed = False
        password_invalid = False
        if user and challenge and active:
            with transaction.atomic():
                challenge = EmailOTPChallenge.objects.select_for_update().get(pk=challenge.pk)
                if challenge.attempts >= MAX_OTP_ATTEMPTS or not challenge.code_hash or not challenge.expires_at or challenge.expires_at <= timezone.now():
                    challenge.code_hash = ""
                    challenge.save(update_fields=("code_hash",))
                elif (
                    len(code) != 6
                    or not code.isascii()
                    or not code.isdigit()
                    or not check_password(code, challenge.code_hash)
                ):
                    challenge.attempts += 1
                    if challenge.attempts >= MAX_OTP_ATTEMPTS:
                        challenge.code_hash = ""
                    challenge.save(update_fields=("attempts", "code_hash"))
                    failed_code = True
                elif password_form and password_form.is_valid():
                    reset_user = password_form.save(commit=False)
                    reset_user.must_change_password = False
                    reset_user.locked_until = None
                    reset_user.save(update_fields=("password", "must_change_password", "locked_until"))
                    challenge.code_hash = ""
                    challenge.completed_at = timezone.now()
                    challenge.save(update_fields=("code_hash", "completed_at"))
                    completed = True
                else:
                    password_invalid = True
        else:
            failure_message = "That code is invalid or expired. Check your email and try again."

        if completed:
            _clear_password_reset_session(request)
            record_auth_event(
                "password_reset_completed",
                email=user.email,
                actor=user,
                description="The account holder reset their password after verifying an email code.",
                request=request,
                factor="email_otp",
                outcome="success",
            )
            messages.success(request, "Your password has been reset. Sign in with your new password.")
            return redirect("login")
        if failed_code:
            record_failed_authentication(
                user.email,
                "password_reset_failure",
                request,
                factor="email_otp",
                description="An invalid password recovery code was submitted.",
            )
            if challenge.attempts >= MAX_OTP_ATTEMPTS:
                failure_message = "That code is invalid or expired. Check your email and try again."
        if not password_invalid:
            messages.error(request, failure_message)
        challenge = EmailOTPChallenge.objects.filter(
            user=user,
            purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
        ).first() if user else None
        now = timezone.now()
        active = bool(
            challenge
            and challenge.code_hash
            and challenge.expires_at
            and challenge.expires_at > now
            and not challenge.completed_at
        )

    # Only show a generic resend cooldown. The server remains authoritative
    # about the real challenge expiry, which can differ when an active code is reused.
    sent_at = request.session.get("authshield_password_reset_sent_at", 0)
    context = {
        "has_reset_request": has_reset_request,
        "password_form": password_form,
        "challenge_active": has_reset_request,
        "otp_resend_available_at": sent_at + settings.AUTHSHIELD_PASSWORD_RESET_OTP_TTL_SECONDS,
    }
    return render(request, "accounts/password_reset_verify.html", context)


@require_POST
def password_reset_resend(request):
    response_started_at = time.monotonic()
    user_id = request.session.get("authshield_password_reset_user_id")
    user = _password_reset_user(pk=user_id) if user_id else None
    challenge = EmailOTPChallenge.objects.filter(
        user=user,
        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
    ).first() if user else None
    if not request.session.get("authshield_password_reset_started_at"):
        return redirect("password_reset_request")

    now = timezone.now()
    seconds_since_send = int((now - challenge.sent_at).total_seconds()) if challenge and challenge.sent_at else 30
    resend_count = request.session.get("authshield_password_reset_resends", 0)
    if resend_count < 3:
        cooldown_active = bool(
            user
            and challenge
            and seconds_since_send < settings.AUTHSHIELD_PASSWORD_RESET_OTP_TTL_SECONDS
        )
        if user and challenge and not cooldown_active:
            if _password_reset_account_send_allowed(user, now):
                try:
                    challenge = start_otp(
                        user.email,
                        "email",
                        request.session,
                        recipient_name=user.full_name,
                        user=user,
                        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
                        force_new=True,
                    )
                except (OTPProviderError, ImproperlyConfigured):
                    pass
                if challenge and getattr(challenge, "_email_sent", False):
                    record_auth_event(
                        "password_reset_otp_sent",
                        email=user.email,
                        actor=user,
                        description="A replacement password recovery code was sent; the prior code is invalid.",
                        request=request,
                        factor="email_otp",
                        outcome="success",
                    )
        request.session["authshield_password_reset_resends"] = resend_count + 1
    else:
        messages.info(request, "This reset request reached its resend limit. Start again later.")
    # Give every visitor the same generic timer and feedback. Actual challenge
    # cooldown, expiry, attempts, and verification remain enforced server-side.
    display_sent_at = timezone.now().timestamp()
    request.session["authshield_password_reset_sent_at"] = display_sent_at
    messages.info(
        request,
        "If an eligible account matches the address, a reset code may be sent. Check your inbox and Spam or Junk folder.",
    )
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    _wait_for_password_reset_response(response_started_at)
    return redirect("password_reset_verify")


class BaselineLogoutView(LogoutView):
    next_page = reverse_lazy("home")

    def post(self, request, *args, **kwargs):
        keycloak_id_token = request.session.get("authshield_keycloak_id_token", "")
        if request.user.is_authenticated:
            record_auth_event(
                "logout_success",
                email=request.user.email,
                actor=request.user,
                description="User signed out.",
                request=request,
                factor="session",
                outcome="success",
            )
            messages.success(request, "You have signed out. This session can no longer be used.")
        if settings.AUTHSHIELD_KEYCLOAK_ENABLED and keycloak_id_token:
            auth_logout(request)
            end_session = (
                f"{settings.AUTHSHIELD_KEYCLOAK_SERVER_URL}/realms/"
                f"{settings.AUTHSHIELD_KEYCLOAK_REALM}/protocol/openid-connect/logout"
            )
            logout_parameters = urlencode({
                "client_id": settings.AUTHSHIELD_KEYCLOAK_CLIENT_ID,
                "id_token_hint": keycloak_id_token,
                "post_logout_redirect_uri": request.build_absolute_uri(reverse_lazy("home")),
            })
            return redirect(f"{end_session}?{logout_parameters}")
        return super().post(request, *args, **kwargs)
@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    if not request.user.must_change_password:
        return redirect("dashboard")
    if settings.AUTHSHIELD_KEYCLOAK_ENABLED:
        if not request.user.keycloak_subject:
            messages.error(request, "This account is not linked to Keycloak yet. Contact the portal administrator.")
            return redirect("login")
        request.session["authshield_keycloak_flow"] = "update_password"
        request.session["authshield_keycloak_password_user_id"] = request.user.pk
        try:
            return keycloak_client().authorize_redirect(
                request,
                request.build_absolute_uri(reverse("keycloak_callback")),
                prompt="login",
                kc_action="UPDATE_PASSWORD",
            )
        except Exception as error:
            logger.warning("Could not start Keycloak password change (%s).", type(error).__name__)
            messages.error(request, "Keycloak is unavailable. Try again later or contact the administrator.")
            return redirect("dashboard")
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.must_change_password = False
        user.save(update_fields=("password", "must_change_password"))
        update_session_auth_hash(request, user)
        record_auth_event(
            "password_reset_completed", email=user.email, actor=user,
            description="A temporary administrator password was replaced by the account holder.",
            request=request, factor="password", outcome="success",
        )
        messages.success(request, "Your password has been changed. You can now use the portal.")
        return redirect("dashboard")
    return render(request, "accounts/password_change.html", {"form": form})
