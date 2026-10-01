"""Forms for administrator-managed portal MFA policy."""

from django import forms


class RoleMFAPolicyForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Require portal MFA for this role")
    sms_enabled = forms.BooleanField(required=False, label="Firebase SMS OTP")
    email_enabled = forms.BooleanField(required=False, label="Email OTP")
    require_both_factors = forms.BooleanField(required=False, label="Require SMS and then email")

    def __init__(self, *args, mandatory=False, require_email=False, mandatory_both=False, **kwargs):
        super().__init__(*args, **kwargs)
        if mandatory:
            self.fields["enabled"].disabled = True
            self.fields["enabled"].initial = True
        if require_email:
            self.fields["email_enabled"].disabled = True
            self.fields["email_enabled"].initial = True
        if mandatory_both:
            for name in ("sms_enabled", "email_enabled", "require_both_factors"):
                self.fields[name].disabled = True
                self.fields[name].initial = True


class MFASaveConfirmationForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label="I understand this applies to all accounts in the selected roles, invalidates pending portal OTP sign-ins, and leaves active sessions signed in.",
        error_messages={"required": "Confirm the MFA changes and their effect on pending sign-ins."},
    )
