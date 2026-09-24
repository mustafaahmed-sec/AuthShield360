"""Public account forms; privileged roles never appear in signup."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import RegexValidator

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
            "minlength": "22",
            "aria-describedby": "password-policy",
        })
        self.fields["password1"].help_text = (
            "Use at least 22 characters, including a lowercase letter, uppercase letter, "
            "number, and special character. A suggested password is available below."
        )
        self.fields["password2"].widget.attrs.update({
            "autocomplete": "new-password",
            "minlength": "22",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.approval_status != User.ApprovalStatus.APPROVED:
            raise forms.ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
                params={"username": self.username_field.verbose_name},
            )
