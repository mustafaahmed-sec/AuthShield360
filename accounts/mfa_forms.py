"""Forms for administrator-managed portal MFA policy."""

from django import forms


class RoleMFAPolicyForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Require portal MFA for this role")
    sms_enabled = forms.BooleanField(required=False, label="Firebase SMS OTP")
    email_enabled = forms.BooleanField(required=False, label="Email OTP")
    require_both_factors = forms.BooleanField(required=False, label="Require SMS and then email")
    include_otp_exempt_accounts = forms.BooleanField(required=False, label="Include OTP-exempt administrator accounts")


class MFASaveConfirmationForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label="I understand this applies to all accounts in the selected roles, invalidates pending portal OTP sign-ins, and leaves active sessions signed in.",
        error_messages={"required": "Confirm the MFA changes and their effect on pending sign-ins."},
    )
