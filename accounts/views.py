import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ImproperlyConfigured, NON_FIELD_ERRORS, PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods
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

from .forms import EmailAuthenticationForm, RegistrationStatusForm, StudentSignupForm, TeacherSignupForm
from django.contrib.auth.forms import SetPasswordForm
from .otp import OTPProviderError, check_otp, delivery_target, start_otp
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
    "authshield_email_otp_hash",
)


def _clear_otp_session(request):
    for key in OTP_SESSION_KEYS:
        request.session.pop(key, None)


def _start_otp(request, user, channel, *, phase="primary", reset_resends=True):
    started_at = timezone.now().timestamp() if phase == "primary" else request.session.get("authshield_otp_started_at")
    start_otp(delivery_target(user, channel), channel, request.session)
    request.session["authshield_otp_user_id"] = user.pk
    request.session["authshield_otp_channel"] = channel
    request.session["authshield_otp_phase"] = phase
    if phase == "primary":
        request.session["authshield_otp_primary_channel"] = channel
    now = timezone.now().timestamp()
    request.session["authshield_otp_sent_at"] = now
    request.session["authshield_otp_expires_at"] = now + settings.AUTHSHIELD_OTP_TTL_SECONDS
    if phase == "primary":
        request.session["authshield_otp_started_at"] = started_at
    request.session["authshield_otp_attempts"] = 0
    if reset_resends:
        request.session["authshield_otp_resends"] = 0
    request.session.set_expiry(settings.AUTHSHIELD_OTP_TTL_SECONDS)


def _otp_duration_ms(request):
    started_at = request.session.get("authshield_otp_started_at")
    if started_at is None:
        return None
    return max(0, int((timezone.now().timestamp() - started_at) * 1000))


def _otp_context(user, channel, phase):
    destination = delivery_target(user, channel)
    if channel == "email":
        local, _, domain = destination.partition("@")
        destination = f"{local[:1]}***@{domain}" if domain else "your email address"
    else:
        destination = f"••••{destination[-4:]}" if len(destination) >= 4 else "your WhatsApp number"
    return {
        "channel": channel,
        "destination": destination,
        "phase": phase,
        "step_up": phase == "email_step_up",
    }


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
            channel = (
                "whatsapp"
                if settings.AUTHSHIELD_EMAIL_STEP_UP
                else (form.cleaned_data.get("otp_channel") or "whatsapp")
            )
            try:
                _start_otp(self.request, user, channel)
            except (OTPProviderError, ImproperlyConfigured):
                record_auth_event(
                    "otp_delivery_failure", email=user.email,
                    description="The configured one-time-code service could not start a challenge.",
                    request=self.request,
                    factor="email_otp" if channel == "email" else "mobile_otp",
                    outcome="failure",
                )
                form.add_error(None, "We could not send a verification code. Try again or choose another method.")
                return self.render_to_response(self.get_context_data(form=form))
            next_url = self.get_redirect_url()
            if next_url and url_has_allowed_host_and_scheme(next_url, {self.request.get_host()}, require_https=self.request.is_secure()):
                self.request.session["authshield_otp_next"] = next_url
            record_auth_event(
                "otp_sent", email=user.email,
                description="A sign-in verification code was requested.",
                request=self.request,
                factor="email_otp" if channel == "email" else "mobile_otp",
                outcome="success",
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
            return render(request, "accounts/otp_verify.html", _otp_context(user, channel, phase), status=429)
        code = (request.POST.get("code") or "").strip()
        attempts = request.session.get("authshield_otp_attempts", 0)
        if attempts >= 5:
            _clear_otp_session(request)
            messages.error(request, "Too many code attempts. Start sign-in again.")
            return redirect("login")
        try:
            approved = check_otp(delivery_target(user, channel), channel, code, request.session)
        except (OTPProviderError, ImproperlyConfigured):
            messages.error(request, "We could not verify that code right now. Try again shortly.")
            return render(request, "accounts/otp_verify.html", _otp_context(user, channel, phase), status=503)
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
            return render(request, "accounts/otp_verify.html", _otp_context(user, channel, phase))

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

        if phase == "primary" and settings.AUTHSHIELD_EMAIL_STEP_UP and channel == "whatsapp":
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
            messages.success(request, "WhatsApp verified. Enter the additional code sent to your email.")
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

    return render(request, "accounts/otp_verify.html", _otp_context(user, channel, phase))


@require_http_methods(["POST"])
def otp_resend(request):
    user_id = request.session.get("authshield_otp_user_id")
    user = User.objects.filter(pk=user_id, is_active=True, approval_status=User.ApprovalStatus.APPROVED).first()
    channel = request.session.get("authshield_otp_channel", "")
    phase = request.session.get("authshield_otp_phase", "primary")
    if not settings.AUTHSHIELD_OTP_ENABLED or not user or channel not in ("whatsapp", "email"):
        _clear_otp_session(request)
        messages.error(request, "Start sign-in again to request a verification code.")
        return redirect("login")
    sent_at = request.session.get("authshield_otp_sent_at", 0)
    if timezone.now().timestamp() >= request.session.get("authshield_otp_expires_at", 0):
        _clear_otp_session(request)
        messages.error(request, "That verification request has expired. Start sign-in again.")
        return redirect("login")
    if timezone.now().timestamp() - sent_at < 60:
        messages.info(request, "Wait one minute before requesting another code.")
        return redirect("otp_verify")
    if request.session.get("authshield_otp_resends", 0) >= 3:
        messages.error(request, "You have reached the resend limit. Start sign-in again later.")
        return redirect("otp_verify")
    try:
        _start_otp(request, user, channel, phase=phase, reset_resends=False)
    except (OTPProviderError, ImproperlyConfigured):
        messages.error(request, "We could not send another code right now.")
        return redirect("otp_verify")
    record_auth_event(
        "otp_sent", email=user.email,
        description="A replacement sign-in verification code was requested.",
        request=request,
        factor="email_otp" if channel == "email" else "mobile_otp",
        outcome="success",
    )
    request.session["authshield_otp_resends"] = request.session.get("authshield_otp_resends", 0) + 1
    messages.success(request, "A new verification code was sent.")
    return redirect("otp_verify")


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
