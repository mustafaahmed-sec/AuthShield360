from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import EmailAuthenticationForm, StudentSignupForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = StudentSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Signup creates an account, but no authenticated session. This makes
        # the authentication stage visible in the demo.
        messages.success(request, "Student account created. Sign in to continue.")
        return redirect("login")
    return render(request, "accounts/signup.html", {"form": form})


class BaselineLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not settings.AUTHSHIELD_BASELINE_LOGIN_ENABLED:
            raise PermissionDenied("The local password-only baseline is disabled.")
        return super().dispatch(request, *args, **kwargs)


class BaselineLogoutView(LogoutView):
    next_page = reverse_lazy("home")
