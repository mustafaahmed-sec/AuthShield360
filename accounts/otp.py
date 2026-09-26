"""Email code delivery and Firebase phone-token verification."""

import secrets
import re
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, ProgrammingError, transaction
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import verify_firebase_token


MAX_OTP_ATTEMPTS = 5


class OTPProviderError(Exception):
    """A provider request failed without exposing provider details to the user."""


class OTPChallengeChanged(Exception):
    """The account's active OTP was replaced, consumed, or otherwise invalidated."""


class OTPChallengeExpired(Exception):
    """The active OTP expired while the verification request was in progress."""


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
    """Send Gmail codes with one active database-backed challenge per account and purpose."""

    SESSION_KEY = "authshield_email_otp_hash"
    EMAIL_CHANNEL = "email"

    def __init__(self):
        self.address = settings.AUTHSHIELD_GMAIL_ADDRESS
        self.app_password = settings.AUTHSHIELD_GMAIL_APP_PASSWORD
        if not self.address or not self.app_password:
            raise ImproperlyConfigured(
                "Gmail email verification is enabled but its server-side settings are incomplete."
            )

    def _send_code(self, destination, code, recipient_name, purpose, ttl_seconds):
        if not destination or "@" not in destination:
            raise OTPProviderError("The account has no usable email address.")
        if ttl_seconds % 60 == 0:
            minutes = ttl_seconds // 60
            expiration = f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            expiration = f"{ttl_seconds} seconds"
        is_reset = purpose == "password_reset"
        context = {
            "code": code,
            "expiration": expiration,
            "recipient_email": destination,
            "recipient_name": (recipient_name or "").strip() or "there",
            "purpose": purpose,
            "is_password_reset": is_reset,
        }
        try:
            message = EmailMultiAlternatives(
                subject=(
                    "Your AuthShield 360 password reset code"
                    if is_reset else "Your AuthShield 360 sign-in code"
                ),
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

    @staticmethod
    def _challenge_table_is_missing(error):
        cause = getattr(error, "__cause__", None)
        sqlstate = getattr(cause, "sqlstate", None)
        message = str(error).lower()
        return sqlstate == "42P01" or "no such table" in message or "does not exist" in message

    def start(self, destination, session, recipient_name="there", *, user=None, purpose="sign_in", force_new=False):
        if not destination or "@" not in destination:
            raise OTPProviderError("The account has no usable email address.")

        if user is not None:
            from .models import EmailOTPChallenge

            try:
                with transaction.atomic():
                    challenge, _ = EmailOTPChallenge.objects.get_or_create(user=user, purpose=purpose)
                    challenge = EmailOTPChallenge.objects.select_for_update().get(pk=challenge.pk)
                    now = timezone.now()
                    if (
                        force_new
                        and challenge.sent_at
                        and (now - challenge.sent_at).total_seconds() < 30
                    ):
                        challenge._email_sent = False
                        return challenge
                    if (
                        not force_new
                        and challenge.code_hash
                        and challenge.expires_at
                        and challenge.expires_at > now
                        and not challenge.completed_at
                    ):
                        challenge._email_sent = False
                        return challenge

                    code = f"{secrets.randbelow(1_000_000):06d}"
                    ttl_seconds = settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS
                    self._send_code(destination, code, recipient_name, purpose, ttl_seconds)
                    sent_at = timezone.now()
                    challenge.code_hash = make_password(code)
                    challenge.sent_at = sent_at
                    challenge.expires_at = sent_at + timedelta(seconds=ttl_seconds)
                    challenge.attempts = 0
                    challenge.completed_at = None
                    challenge.save(update_fields=("code_hash", "sent_at", "expires_at", "attempts", "completed_at"))
                    challenge._email_sent = True
                    return challenge
            except (OperationalError, ProgrammingError) as error:
                if not self._challenge_table_is_missing(error):
                    raise
                if purpose == "password_reset":
                    raise ImproperlyConfigured("Apply account migrations before enabling password reset codes.") from error

        # Compatibility for isolated callers that do not have an authenticated user record.
        session.pop(self.SESSION_KEY, None)
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._send_code(destination, code, recipient_name, purpose, settings.AUTHSHIELD_EMAIL_OTP_TTL_SECONDS)
        session[self.SESSION_KEY] = make_password(code)
        return None

    def check(self, code, session, *, user=None, purpose="sign_in", expected_sent_at=None):
        code_has_valid_format = bool(re.fullmatch(r"[0-9]{6}", code or ""))
        if user is not None:
            from .models import EmailOTPChallenge, User

            try:
                with transaction.atomic():
                    challenge = EmailOTPChallenge.objects.select_for_update().filter(
                        user=user,
                        purpose=purpose,
                    ).first()
                    now = timezone.now()
                    if expected_sent_at is not None:
                        if not challenge:
                            raise OTPChallengeChanged
                        try:
                            expected_sent_at = float(expected_sent_at)
                        except (TypeError, ValueError):
                            raise OTPChallengeChanged
                        if (
                            not challenge.sent_at
                            or abs(challenge.sent_at.timestamp() - expected_sent_at) > 0.001
                            or challenge.completed_at
                            or not challenge.code_hash
                        ):
                            raise OTPChallengeChanged
                        if not challenge.expires_at or challenge.expires_at <= now:
                            raise OTPChallengeExpired
                    if (
                        not challenge
                        or not challenge.code_hash
                        or not challenge.expires_at
                        or challenge.expires_at <= now
                        or challenge.completed_at
                    ):
                        return False
                    if user.role != User.Role.ADMIN and challenge.attempts >= MAX_OTP_ATTEMPTS:
                        challenge.code_hash = ""
                        challenge.save(update_fields=("code_hash",))
                        return False
                    if not code_has_valid_format or not check_password(code, challenge.code_hash):
                        if user.role == User.Role.ADMIN:
                            return False
                        challenge.attempts += 1
                        update_fields = ["attempts"]
                        if challenge.attempts >= MAX_OTP_ATTEMPTS:
                            challenge.code_hash = ""
                            update_fields.append("code_hash")
                        challenge.save(update_fields=update_fields)
                        return False
                    challenge.code_hash = ""
                    challenge.completed_at = now
                    challenge.save(update_fields=("code_hash", "completed_at"))
                    return True
            except (OperationalError, ProgrammingError) as error:
                if not self._challenge_table_is_missing(error):
                    raise
                if purpose == "password_reset":
                    raise ImproperlyConfigured("Apply account migrations before enabling password reset codes.") from error
        if not code_has_valid_format:
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


def start_otp(destination, channel, session, recipient_name="there", *, user=None, purpose="sign_in", force_new=False):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return GmailEmailOTP().start(
            destination,
            session,
            recipient_name,
            user=user,
            purpose=purpose,
            force_new=force_new,
        )
    raise ImproperlyConfigured("SMS codes are sent and verified in the Firebase phone-auth page.")


def check_otp(destination, channel, code, session, *, user=None, purpose="sign_in", expected_sent_at=None):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return GmailEmailOTP().check(
            code,
            session,
            user=user,
            purpose=purpose,
            expected_sent_at=expected_sent_at,
        )
    return False
