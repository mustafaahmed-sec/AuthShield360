import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

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
from school.audit import record_auth_event


User = get_user_model()


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
        if not settings.AUTHSHIELD_BASELINE_LOGIN_ENABLED:
            raise PermissionDenied("The local password-only baseline is disabled.")
        return super().dispatch(request, *args, **kwargs)

    def _duration_ms(self):
        return max(0, int((time.monotonic() - self._auth_started_at) * 1000))

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
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
        return response

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
