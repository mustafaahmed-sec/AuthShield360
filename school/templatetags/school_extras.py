from django import template

register = template.Library()

_EVENT_LABELS = {
    "loginsuccess": "Login success",
    "loginfailure": "Login failure",
    "registrationstatussuccess": "Registration status success",
    "registrationstatusfailure": "Registration status failure",
    "otpsent": "OTP sent",
    "otpsuccess": "OTP success",
    "otpfailure": "OTP failure",
    "otpexpired": "OTP expired",
    "otpdeliveryfailure": "OTP delivery failure",
    "logoutsuccess": "Logout success",
    "lockedout": "Locked out",
    "ipratelimited": "IP rate limited",
    "roleaccessdenied": "Role access denied",
    "passwordresetcompleted": "Password reset completed",
    "accountpasswordreset": "Account password reset",
    "studentpasswordreset": "Student password reset",
}


@register.filter
def spaced_words(value):
    """Turn event keys, including older concatenated keys, into readable labels."""
    text = str(value).strip()
    compact = "".join(character for character in text.casefold() if character.isalnum())
    if compact in _EVENT_LABELS:
        return _EVENT_LABELS[compact]
    return text.replace("_", " ").replace("-", " ")
