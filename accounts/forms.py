"""Public account forms; privileged roles never appear in signup."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import RegexValidator
from django.utils import timezone

from .lockout import account_lockout_until, ip_throttle_until, retry_minutes
from .models import User


class AccountSignupForm(UserCreationForm):
    requested_role = User.Role.STUDENT
    phone_number = forms.CharField(
        label="Phone number",
        max_length=32,
        validators=[RegexValidator(r"^\+?[0-9][0-9\s().-]{6,30}$", "Enter a valid test phone number.")],
        help_text="Use fictional contact details for this demonstration.",
    )

    class Meta:
        model = User
        fields = ("full_name", "email", "phone_number")
        labels = {"full_name": "Full name", "phone_number": "Phone number"}
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your full name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.test"}),
        }

    def __init__(self, *args, **kwargs):
        data = args[0] if args else kwargs.get("data")
        if data and not kwargs.get("instance"):
            email = data.get("email", "").strip().lower()
            password = data.get("password1", "")
            existing = User.objects.filter(email__iexact=email).first() if email else None
            if (
                existing
                and existing.role == self.requested_role
                and existing.approval_status == User.ApprovalStatus.REJECTED
                and existing.check_password(password)
            ):
                kwargs["instance"] = existing
        super().__init__(*args, **kwargs)
        self.fields["full_name"].required = True
        self.fields["email"].required = True
        self.fields["password1"].widget.attrs.update({
            "autocomplete": "new-password",
            "minlength": "12",
            "maxlength": "50",
            "aria-describedby": "password-policy",
        })
        self.fields["password1"].help_text = (
            "Use 12–50 characters, including a lowercase letter, uppercase letter, "
            "number, and special character. A suggested password is available below."
        )
        self.fields["password2"].widget.attrs.update({
            "autocomplete": "new-password",
            "minlength": "12",
            "maxlength": "50",
        })

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("We could not submit this request. Check your details or contact the administrator.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.requested_role
        user.is_staff = False
        user.is_superuser = False
        user.is_active = False
        user.approval_status = User.ApprovalStatus.PENDING
        user.reviewed_at = None
        user.reviewed_by = None
        if commit:
            user.save()
        return user


class StudentSignupForm(AccountSignupForm):
    requested_role = User.Role.STUDENT


class TeacherSignupForm(AccountSignupForm):
    requested_role = User.Role.TEACHER


class RegistrationStatusForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "username"}))
    otp_channel = forms.ChoiceField(
        label="Send the sign-in code by",
        choices=(("whatsapp", "WhatsApp"), ("email", "Email")),
        initial="email",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})

    def clean(self):
        email = self.data.get(self.add_prefix(self.username_field), "").strip().lower()
        now = timezone.now()
        ip_until = ip_throttle_until(self.request, now)
        if ip_until:
            raise forms.ValidationError(
                f"Too many attempts. Try again in {retry_minutes(ip_until, now)} minutes.",
                code="ip_rate_limited",
            )
        lock_until = account_lockout_until(email, now)
        if lock_until:
            raise forms.ValidationError(
                f"Too many attempts. Try again in {retry_minutes(lock_until, now)} minutes.",
                code="account_locked",
            )
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.locked_until and user.locked_until > timezone.now():
            raise forms.ValidationError(
                f"Too many attempts. Try again in {retry_minutes(user.locked_until)} minutes.",
                code="account_locked",
            )
        if user.approval_status != User.ApprovalStatus.APPROVED:
            raise forms.ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
                params={"username": self.username_field.verbose_name},
            )
