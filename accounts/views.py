from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

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
        user = form.save()
        messages.success(
            request,
            f"Your {role_label} access request was submitted. An administrator must approve it before you can sign in.",
        )
        return redirect("registration_status")
    return render(request, "accounts/signup.html", {"form": form, "role": role, "role_label": role_label})


def registration_status(request):
    form = RegistrationStatusForm(request.POST or None)
    result = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password"]
        user = User.objects.filter(email__iexact=email).first()
        if user and user.check_password(password) and user.role in (User.Role.STUDENT, User.Role.TEACHER):
            if user.approval_status == User.ApprovalStatus.PENDING:
                result = "pending"
            elif user.approval_status == User.ApprovalStatus.APPROVED and user.is_active:
                result = "approved"
            else:
                result = "not_approved"
        else:
            form.add_error(None, "We could not check this request. Verify the details and try again.")
    return render(request, "accounts/registration_status.html", {"form": form, "result": result})


class BaselineLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not settings.AUTHSHIELD_BASELINE_LOGIN_ENABLED:
            raise PermissionDenied("The local password-only baseline is disabled.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        record_auth_event(
            "login_success",
            email=form.get_user().email,
            actor=form.get_user(),
            description="Successful password-only sign-in.",
        )
        return response

    def form_invalid(self, form):
        email = self.request.POST.get("username", "").strip().lower()
        record_auth_event(
            "login_failure",
            email=email,
            description="Failed password-only sign-in.",
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
            )
        return super().post(request, *args, **kwargs)
