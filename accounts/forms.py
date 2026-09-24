"""Public account forms; privileged roles never appear in signup."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import RegexValidator

from .models import User


class StudentSignupForm(UserCreationForm):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].required = True
        self.fields["email"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email address is already registered.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STUDENT
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email address", widget=forms.EmailInput(attrs={"autocomplete": "username"}))
