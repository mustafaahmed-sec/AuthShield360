import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ImproperlyConfigured, NON_FIELD_ERRORS, PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required

from .lockout import (
    account_lockout_until,
    clear_expired_or_successful_lock,
    ip_throttle_until,
    normalized_email,
    record_blocked_attempt,
    record_failed_authentication,
    retry_minutes,
)

from .forms import (
    EmailAuthenticationForm,
    PasswordResetRequestForm,
    RegistrationStatusForm,
    StudentSignupForm,
    TeacherSignupForm,
)
from django.contrib.auth.forms import SetPasswordForm
from .models import EmailOTPChallenge
from .otp import (
    OTPProviderError,
    check_otp,
    delivery_target,
    firebase_phone_auth_available,
    start_otp,
    verify_firebase_phone_id_token,
)
from school.audit import record_auth_event


User = get_user_model()
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
    "authshield_otp_sms_sent_at",
    "authshield_otp_sms_send_authorized_at",
    "authshield_otp_sms_sent",
    "authshield_email_otp_hash",
)


def _clear_otp_session(request):
    for key in OTP_SESSION_KEYS:
        request.session.pop(key, None)


def _otp_ttl_seconds(channel):
    if channel == "email":
        return settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
    if channel == "sms":
        return settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    return settings.AUTHSHIELD_OTP_TTL_SECONDS


def _start_otp(request, user, channel, *, phase="primary", reset_resends=True, force_new=False):
    purpose = "email_step_up" if phase == "email_step_up" else "sign_in"
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
    if reset_resends:
        request.session["authshield_otp_resends"] = 0
    request.session.set_expiry(max(1, int(expires_at - now)))
    return challenge


def _prepare_firebase_sms_challenge(request, user):
    if not firebase_phone_auth_available():
        raise ImproperlyConfigured("Firebase Phone Authentication is not configured.")
    if not delivery_target(user, "sms"):
        raise OTPProviderError("This account has no valid international phone number.")
    _clear_otp_session(request)
    now = timezone.now().timestamp()
    request.session["authshield_otp_user_id"] = user.pk
    request.session["authshield_otp_channel"] = "sms"
    request.session["authshield_otp_phase"] = "primary"
    request.session["authshield_otp_primary_channel"] = "sms"
    request.session["authshield_otp_started_at"] = now
    request.session["authshield_otp_expires_at"] = now + settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    request.session["authshield_otp_attempts"] = 0
    request.session["authshield_otp_resends"] = 0
    request.session["authshield_otp_sms_sent"] = False
    request.session.set_expiry(settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS)


def _otp_duration_ms(request):
    started_at = request.session.get("authshield_otp_started_at")
    if started_at is None:
        return None
    return max(0, int((timezone.now().timestamp() - started_at) * 1000))


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
        "step_up": phase == "email_step_up",
        "otp_sms_sent": channel != "sms" or bool(request.session.get("authshield_otp_sms_sent")),
        "otp_expires_at": request.session.get("authshield_otp_expires_at", 0),
        "otp_resend_available_at": request.session.get("authshield_otp_sent_at", 0) + 30,
    }
    if channel == "sms":
        context.update({
            "firebase_phone_config": {
                "apiKey": settings.AUTHSHIELD_FIREBASE_API_KEY,
                "authDomain": settings.AUTHSHIELD_FIREBASE_AUTH_DOMAIN,
                "projectId": settings.AUTHSHIELD_FIREBASE_PROJECT_ID,
                "appId": settings.AUTHSHIELD_FIREBASE_APP_ID,
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
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            f"Your {role_label} access request was submitted. An administrator must approve it before you can sign in.",
        )
        return redirect("registration_status")
    return render(request, "accounts/signup.html", {"form": form, "role": role, "role_label": role_label})


def signup_options(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "accounts/signup_options.html")


def registration_status(request):
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
    return render(request, "accounts/registration_status.html", {"form": form, "result": result})


class BaselineLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        self._auth_started_at = time.monotonic()
        if not settings.AUTHSHIELD_LOGIN_ENABLED:
            raise PermissionDenied("Sign-in is disabled until the authentication stage is configured.")
        return super().dispatch(request, *args, **kwargs)

    def _duration_ms(self):
        return max(0, int((time.monotonic() - self._auth_started_at) * 1000))

    def form_valid(self, form):
        user = form.get_user()
        if settings.AUTHSHIELD_OTP_ENABLED:
            if settings.AUTHSHIELD_EMAIL_STEP_UP:
                channel = "sms"
            elif firebase_phone_auth_available():
                channel = form.cleaned_data.get("otp_channel") or "email"
            else:
                channel = "email"
            if channel == "sms":
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
            duration_ms=self._duration_ms(),
        )
        if user.must_change_password:
            return redirect("password_change")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["otp_enabled"] = settings.AUTHSHIELD_OTP_ENABLED
        context["email_step_up"] = settings.AUTHSHIELD_EMAIL_STEP_UP
        context["mobile_otp_enabled"] = firebase_phone_auth_available()
        context["lockout_until"] = 0
        if self.request.method == "POST":
            email = normalized_email(self.request.POST.get("username", ""))
            now = timezone.now()
            account_until = account_lockout_until(email, now)
            source_until = ip_throttle_until(self.request, now)
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
        else:
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
    if not settings.AUTHSHIELD_OTP_ENABLED or not user_id:
        _clear_otp_session(request)
        messages.info(request, "Start sign-in again to request a verification code.")
        return redirect("login")
    user = User.objects.filter(pk=user_id, is_active=True, approval_status=User.ApprovalStatus.APPROVED).first()
    if not user or (user.locked_until and user.locked_until > timezone.now()):
        _clear_otp_session(request)
        messages.error(request, "Sign-in could not continue. Start again or contact the administrator.")
        return redirect("login")

    channel = request.session.get("authshield_otp_channel", "")
    phase = request.session.get("authshield_otp_phase", "primary")
    if timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        record_failed_authentication(
            user.email,
            "otp_failure",
            request,
            duration_ms=_otp_duration_ms(request),
            factor="email_otp" if channel == "email" else "mobile_otp",
            description="A one-time code was submitted after its verification window expired.",
        )
        _clear_otp_session(request)
        messages.error(request, "That verification code has expired. Start sign-in again.")
        return redirect("login")
    if request.method == "POST":
        now = timezone.now()
        source_until = ip_throttle_until(request, now)
        if source_until:
            record_blocked_attempt(user.email, request, action="ip_rate_limited")
            messages.error(request, f"Too many attempts. Try again in {retry_minutes(source_until, now)} minutes.")
            return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=429)
        code = (request.POST.get("code") or "").strip()
        attempts = request.session.get("authshield_otp_attempts", 0)
        if attempts >= 5:
            _clear_otp_session(request)
            messages.error(request, "Too many code attempts. Start sign-in again.")
            return redirect("login")
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
                purpose = "email_step_up" if phase == "email_step_up" else "sign_in"
                approved = check_otp(
                    delivery_target(user, channel),
                    channel,
                    code,
                    request.session,
                    user=user,
                    purpose=purpose,
                )
            except (OTPProviderError, ImproperlyConfigured):
                messages.error(request, "We could not verify that code right now. Try again shortly.")
                return render(request, "accounts/otp_verify.html", _otp_context(request, user, channel, phase), status=503)
        if not approved:
            request.session["authshield_otp_attempts"] = attempts + 1
            record_failed_authentication(
                user.email,
                "otp_failure",
                request,
                factor="email_otp" if channel == "email" else "mobile_otp",
                duration_ms=_otp_duration_ms(request),
                description="An invalid or expired one-time code was submitted.",
            )
            user.refresh_from_db(fields=["locked_until"])
            if user.locked_until and user.locked_until > timezone.now():
                _clear_otp_session(request)
                messages.error(request, "Too many attempts. The account is temporarily locked.")
                return redirect("login")
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

        if phase == "primary" and settings.AUTHSHIELD_EMAIL_STEP_UP and channel == "sms":
            try:
                _start_otp(request, user, "email", phase="email_step_up")
            except (OTPProviderError, ImproperlyConfigured):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="Email step-up verification could not be started.",
                    request=request, factor="email_otp", outcome="failure",
                )
                messages.error(request, "Email verification could not be sent. Sign-in has not completed.")
                _clear_otp_session(request)
                return redirect("login")
            record_auth_event(
                "otp_sent", email=user.email,
                description="The additional email verification code was requested.",
                request=request, factor="email_otp", outcome="success",
            )
            messages.success(request, "SMS verified. Enter the additional code sent to your email.")
            return redirect("otp_verify")

        auth_mode = "otp_email" if phase == "email_step_up" else "otp"
        duration_ms = _otp_duration_ms(request)
        next_url = request.session.get("authshield_otp_next") or settings.LOGIN_REDIRECT_URL
        _clear_otp_session(request)
        clear_expired_or_successful_lock(user)
        login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
        record_auth_event(
            "login_success",
            email=user.email,
            actor=user,
            description="Successful password and one-time-code sign-in.",
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


def _pending_sms_user(request):
    user_id = request.session.get("authshield_otp_user_id")
    if (
        not settings.AUTHSHIELD_OTP_ENABLED
        or request.session.get("authshield_otp_channel") != "sms"
        or not firebase_phone_auth_available()
    ):
        return None
    user = User.objects.filter(
        pk=user_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    ).first()
    if not user or (user.locked_until and user.locked_until > timezone.now()):
        return None
    if timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        return None
    if not delivery_target(user, "sms"):
        return None
    return user


@require_POST
def otp_sms_authorize_send(request):
    user = _pending_sms_user(request)
    if not user:
        return JsonResponse({"error": "Restart sign-in before requesting an SMS code."}, status=400)
    now = timezone.now().timestamp()
    sent_at = request.session.get("authshield_otp_sms_sent_at")
    if sent_at:
        remaining = 60 - int(now - sent_at)
        if remaining > 0:
            return JsonResponse({"error": f"Wait {remaining} seconds before requesting another SMS."}, status=429)
        if request.session.get("authshield_otp_resends", 0) >= 3:
            return JsonResponse({"error": "You have reached the SMS resend limit. Restart sign-in later."}, status=429)
        request.session["authshield_otp_resends"] = request.session.get("authshield_otp_resends", 0) + 1
    request.session["authshield_otp_sms_sent_at"] = now
    request.session["authshield_otp_sms_send_authorized_at"] = now
    request.session["authshield_otp_sms_sent"] = False
    request.session.save()
    return JsonResponse({"ok": True})


@require_POST
def otp_sms_mark_sent(request):
    user = _pending_sms_user(request)
    authorized_at = request.session.get("authshield_otp_sms_send_authorized_at", 0)
    if not user or not authorized_at or timezone.now().timestamp() - authorized_at > 120:
        return JsonResponse({"error": "The SMS request expired. Request a new code."}, status=400)
    request.session["authshield_otp_sms_sent"] = True
    now = timezone.now().timestamp()
    request.session["authshield_otp_sent_at"] = now
    request.session["authshield_otp_started_at"] = now
    request.session["authshield_otp_expires_at"] = now + settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS
    request.session.set_expiry(settings.AUTHSHIELD_SMS_OTP_TTL_SECONDS)
    request.session.save()
    record_auth_event(
        "otp_sent", email=user.email,
        description="Firebase accepted the SMS verification request.",
        request=request, factor="mobile_otp", outcome="success",
    )
    return JsonResponse({
        "ok": True,
        "sentAt": now,
        "expiresAt": request.session["authshield_otp_expires_at"],
        "resendAvailableAt": now + 60,
    })


@require_POST
def otp_sms_record_failure(request):
    user = _pending_sms_user(request)
    if not user:
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
    user.refresh_from_db(fields=["locked_until"])
    if (user.locked_until and user.locked_until > timezone.now()) or attempts >= 5:
        _clear_otp_session(request)
        return JsonResponse({"error": "Too many code attempts. Restart sign-in later."}, status=429)
    request.session.save()
    return JsonResponse({"ok": True, "remainingAttempts": 5 - attempts})


@require_http_methods(["POST"])
def otp_resend(request):
    user_id = request.session.get("authshield_otp_user_id")
    user = User.objects.filter(pk=user_id, is_active=True, approval_status=User.ApprovalStatus.APPROVED).first()
    channel = request.session.get("authshield_otp_channel", "")
    phase = request.session.get("authshield_otp_phase", "primary")
    if not settings.AUTHSHIELD_OTP_ENABLED or not user or channel != "email":
        _clear_otp_session(request)
        messages.error(request, "Start sign-in again to request a verification code.")
        return redirect("login")
    sent_at = request.session.get("authshield_otp_sent_at", 0)
    if timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        _clear_otp_session(request)
        messages.error(request, "That verification request has expired. Start sign-in again.")
        return redirect("login")
    resend_cooldown_seconds = 30
    if timezone.now().timestamp() - sent_at < resend_cooldown_seconds:
        messages.info(request, "Wait 30 seconds before requesting another email code.")
        return redirect("otp_verify")
    if request.session.get("authshield_otp_resends", 0) >= 3:
        messages.error(request, "You have reached the resend limit. Start sign-in again later.")
        return redirect("otp_verify")
    try:
        challenge = _start_otp(request, user, channel, phase=phase, reset_resends=False, force_new=True)
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


@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _clear_otp_session(request)
        _clear_password_reset_session(request)
        now = timezone.now().timestamp()
        request.session["authshield_password_reset_started_at"] = now
        request.session["authshield_password_reset_sent_at"] = now
        request.session["authshield_password_reset_expires_at"] = now + settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
        request.session["authshield_password_reset_resends"] = 0
        request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        email = normalized_email(form.cleaned_data["email"])
        user = User.objects.filter(
            email__iexact=email,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        ).first()
        if user:
            # Keep the eligible account in this browser session so a transient
            # mail-delivery failure can be retried from the same generic page.
            request.session["authshield_password_reset_user_id"] = user.pk
            try:
                challenge = start_otp(
                    user.email,
                    "email",
                    request.session,
                    recipient_name=user.full_name,
                    user=user,
                    purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
                )
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
                expires_at = challenge.expires_at.timestamp() if challenge and challenge.expires_at else 0
                sent_at = challenge.sent_at.timestamp() if challenge and challenge.sent_at else now
                request.session["authshield_password_reset_sent_at"] = sent_at
                request.session["authshield_password_reset_expires_at"] = expires_at
                request.session.set_expiry(settings.SESSION_COOKIE_AGE)
                record_auth_event(
                    "password_reset_otp_sent",
                    email=user.email,
                    actor=user,
                    description="A password recovery code was sent or an active code was reused.",
                    request=request,
                    factor="email_otp",
                    outcome="success",
                )
        # Keep the response the same for known and unknown addresses.
        return redirect("password_reset_verify")
    return render(request, "accounts/password_reset_request.html", {"form": form})


@require_http_methods(["GET", "POST"])
def password_reset_verify(request):
    user_id = request.session.get("authshield_password_reset_user_id")
    user = User.objects.filter(
        pk=user_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    ).first() if user_id else None
    challenge = EmailOTPChallenge.objects.filter(
        user=user,
        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
    ).first() if user else None
    has_reset_request = bool(request.session.get("authshield_password_reset_started_at"))
    password_form = SetPasswordForm(user, request.POST or None) if has_reset_request else None
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
                if challenge.attempts >= 5 or not challenge.code_hash or not challenge.expires_at or challenge.expires_at <= timezone.now():
                    challenge.code_hash = ""
                    challenge.save(update_fields=("code_hash",))
                elif not check_password(code, challenge.code_hash):
                    challenge.attempts += 1
                    if challenge.attempts >= 5:
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
            if challenge.attempts >= 5:
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

    expires_at = request.session.get("authshield_password_reset_expires_at", 0)
    sent_at = request.session.get("authshield_password_reset_sent_at", 0)
    if user and challenge:
        sent_at = challenge.sent_at.timestamp() if challenge.sent_at else sent_at
        expires_at = challenge.expires_at.timestamp() if challenge.expires_at else expires_at
        if challenge.completed_at or not challenge.code_hash:
            expires_at = min(expires_at, now.timestamp()) if expires_at else now.timestamp()
        request.session["authshield_password_reset_sent_at"] = sent_at
        request.session["authshield_password_reset_expires_at"] = expires_at
    context = {
        "has_reset_request": has_reset_request,
        "password_form": password_form,
        "challenge_active": has_reset_request,
        "otp_expires_at": expires_at,
        "otp_resend_available_at": sent_at + 30,
    }
    return render(request, "accounts/password_reset_verify.html", context)


@require_POST
def password_reset_resend(request):
    user_id = request.session.get("authshield_password_reset_user_id")
    user = User.objects.filter(
        pk=user_id,
        is_active=True,
        approval_status=User.ApprovalStatus.APPROVED,
    ).first() if user_id else None
    challenge = EmailOTPChallenge.objects.filter(
        user=user,
        purpose=EmailOTPChallenge.Purpose.PASSWORD_RESET,
    ).first() if user else None
    if not request.session.get("authshield_password_reset_started_at"):
        return redirect("password_reset_request")

    now = timezone.now()
    seconds_since_send = int((now - challenge.sent_at).total_seconds()) if challenge and challenge.sent_at else 30
    if user and challenge and seconds_since_send < 30:
        return redirect("password_reset_verify")
    resend_count = request.session.get("authshield_password_reset_resends", 0)
    if resend_count < 3:
        if user and challenge:
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
                messages.error(request, "We could not send a new code right now. Try again later.")
            if challenge and getattr(challenge, "_email_sent", False):
                request.session["authshield_password_reset_sent_at"] = challenge.sent_at.timestamp()
                request.session["authshield_password_reset_expires_at"] = challenge.expires_at.timestamp()
                record_auth_event(
                    "password_reset_otp_sent",
                    email=user.email,
                    actor=user,
                    description="A replacement password recovery code was sent; the prior code is invalid.",
                    request=request,
                    factor="email_otp",
                    outcome="success",
                )
            elif challenge and not getattr(challenge, "_email_sent", True):
                messages.info(request, "A code was recently sent. Check that message, then wait before requesting another.")
        now = timezone.now().timestamp()
        request.session["authshield_password_reset_resends"] = resend_count + 1
        if not user or not challenge:
            request.session["authshield_password_reset_sent_at"] = now
            request.session["authshield_password_reset_expires_at"] = now + settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
    else:
        messages.info(request, "This reset request reached its resend limit. Start again later.")
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    return redirect("password_reset_verify")


class BaselineLogoutView(LogoutView):
    next_page = reverse_lazy("home")

    def post(self, request, *args, **kwargs):
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
        return super().post(request, *args, **kwargs)
@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    if not request.user.must_change_password:
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
