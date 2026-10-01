"""Forms for administrator-managed portal MFA policy."""

from django import forms


class RoleMFAPolicyForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Require portal MFA for this role")
    sms_enabled = forms.BooleanField(required=False, label="Firebase SMS OTP")
    email_enabled = forms.BooleanField(required=False, label="Email OTP")
    require_both_factors = forms.BooleanField(required=False, label="Require SMS and then email")

class MFASaveConfirmationForm(forms.Form):
    confirm = forms.BooleanField(
        required=True,
        label="I understand this applies to every account in the selected roles. Disabling MFA skips portal OTP at the next sign-in. Changed settings invalidate pending portal OTP sign-ins, while active sessions stay signed in.",
        error_messages={"required": "Confirm the MFA changes and their effect on pending sign-ins."},
    )
