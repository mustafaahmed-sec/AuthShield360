"""Email code delivery and Firebase phone-token verification."""

import secrets
import re
import smtplib

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import verify_firebase_token


class OTPProviderError(Exception):
    """A provider request failed without exposing provider details to the user."""


class FirebaseTokenRequest(GoogleAuthRequest):
    """Bound certificate-fetch time so token checks cannot stall a portal request."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=8, **kwargs):
        return super().__call__(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=min(timeout or 8, 8),
            **kwargs,
        )


def firebase_phone_auth_available():
    """Return whether this deployment has the Firebase web configuration it needs."""
    return all((
        settings.AUTHSHIELD_FIREBASE_API_KEY,
        settings.AUTHSHIELD_FIREBASE_AUTH_DOMAIN,
        settings.AUTHSHIELD_FIREBASE_PROJECT_ID,
        settings.AUTHSHIELD_FIREBASE_APP_ID,
    ))


def normalize_phone_number(value):
    """Convert supported phone input to E.164, including Pakistani local numbers."""
    value = (value or "").strip()
    if not value or not re.fullmatch(r"\+?[0-9\s().-]{7,32}", value):
        return ""
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        candidate = f"+{digits}"
    elif digits.startswith("00"):
        candidate = f"+{digits[2:]}"
    elif len(digits) == 11 and digits.startswith("03"):
        candidate = f"+92{digits[1:]}"
    elif len(digits) == 10 and digits.startswith("3"):
        candidate = f"+92{digits}"
    else:
        candidate = f"+{digits}"
    return candidate if re.fullmatch(r"\+[1-9][0-9]{7,14}", candidate) else ""


def verify_firebase_phone_id_token(id_token, *, expected_phone, minimum_auth_time):
    """Verify a client Firebase token and require fresh authentication by phone."""
    if not firebase_phone_auth_available():
        raise ImproperlyConfigured("Firebase Phone Authentication is not configured.")
    if not id_token or len(id_token) > 8192:
        return None
    try:
        claims = verify_firebase_token(
            id_token,
            FirebaseTokenRequest(),
            audience=settings.AUTHSHIELD_FIREBASE_PROJECT_ID,
        )
    except ValueError:
        return None
    except GoogleAuthError as error:
        raise OTPProviderError("Firebase could not verify the sign-in token.") from error

    firebase_claims = claims.get("firebase") or {}
    try:
        auth_time = int(claims.get("auth_time", 0))
    except (TypeError, ValueError):
        return None
    if (
        firebase_claims.get("sign_in_provider") != "phone"
        or auth_time < int(minimum_auth_time) - 10
        or normalize_phone_number(claims.get("phone_number")) != expected_phone
    ):
        return None
    return claims


class GmailEmailOTP:
    """Send email codes through Gmail SMTP and verify them against the session."""

    SESSION_KEY = "authshield_email_otp_hash"
    EMAIL_CHANNEL = "email"

    def __init__(self):
        self.address = settings.AUTHSHIELD_GMAIL_ADDRESS
        self.app_password = settings.AUTHSHIELD_GMAIL_APP_PASSWORD
        if not self.address or not self.app_password:
            raise ImproperlyConfigured(
                "Gmail email verification is enabled but its server-side settings are incomplete."
            )

    def start(self, destination, session, recipient_name="there"):
        if not destination or "@" not in destination:
            raise OTPProviderError("The account has no usable email address.")
        session.pop(self.SESSION_KEY, None)
        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl_seconds = settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
        if ttl_seconds % 60 == 0:
            minutes = ttl_seconds // 60
            expiration = f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            expiration = f"{ttl_seconds} seconds"
        context = {
            "code": code,
            "expiration": expiration,
            "recipient_email": destination,
            "recipient_name": (recipient_name or "").strip() or "there",
        }
        try:
            message = EmailMultiAlternatives(
                subject="Your AuthShield 360 sign-in code",
                body=render_to_string("emails/otp_email.txt", context),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[destination],
            )
            message.attach_alternative(
                render_to_string("emails/otp_email.html", context),
                "text/html",
            )
            sent = message.send(fail_silently=False)
        except (OSError, smtplib.SMTPException, TimeoutError) as error:
            raise OTPProviderError("Gmail could not send the verification email.") from error
        if sent != 1:
            raise OTPProviderError("Gmail did not accept the verification email.")
        session[self.SESSION_KEY] = make_password(code)

    def check(self, code, session):
        if not re.fullmatch(r"[0-9]{6}", code or ""):
            return False
        code_hash = session.get(self.SESSION_KEY)
        if not code_hash or not check_password(code, code_hash):
            return False
        session.pop(self.SESSION_KEY, None)
        return True


def delivery_target(user, channel):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return user.email
    return normalize_phone_number(user.phone_number)


def start_otp(destination, channel, session, recipient_name="there"):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        GmailEmailOTP().start(destination, session, recipient_name)
        return
    raise ImproperlyConfigured("SMS codes are sent and verified in the Firebase phone-auth page.")


def check_otp(destination, channel, code, session):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return GmailEmailOTP().check(code, session)
    return False
