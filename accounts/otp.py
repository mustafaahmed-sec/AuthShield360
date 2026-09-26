"""Delivery adapters for email and mobile one-time codes."""

import base64
import json
import secrets
import re
import smtplib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


class OTPProviderError(Exception):
    """A provider request failed without exposing provider details to the user."""


def mobile_otp_available():
    """Return whether a mobile OTP provider is configured for this deployment."""
    return all((
        settings.TWILIO_API_KEY_SID,
        settings.TWILIO_API_KEY_SECRET,
        settings.TWILIO_VERIFY_SERVICE_SID,
    ))


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


class TwilioVerify:
    """Twilio Verify adapter reserved for mobile channels such as WhatsApp or SMS."""

    API_ROOT = "https://verify.twilio.com/v2/Services"
    WHATSAPP_CHANNEL = "whatsapp"
    SMS_CHANNEL = "sms"

    def __init__(self):
        self.key_sid = settings.TWILIO_API_KEY_SID
        self.key_secret = settings.TWILIO_API_KEY_SECRET
        self.service_sid = settings.TWILIO_VERIFY_SERVICE_SID
        if not all((self.key_sid, self.key_secret, self.service_sid)):
            raise ImproperlyConfigured("Twilio Verify is enabled but its server-side settings are incomplete.")
        if not re.fullmatch(r"VA[0-9a-fA-F]{32}", self.service_sid):
            raise ImproperlyConfigured("TWILIO_VERIFY_SERVICE_SID must be a Verify Service SID.")
        if not re.fullmatch(r"SK[0-9a-fA-F]{32}", self.key_sid):
            raise ImproperlyConfigured("TWILIO_API_KEY_SID must be an API Key SID.")

    def start(self, destination, channel):
        if channel not in (self.WHATSAPP_CHANNEL, self.SMS_CHANNEL):
            raise OTPProviderError("Unsupported verification channel.")
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", destination or ""):
            raise OTPProviderError("The account has no usable phone number.")
        result = self._post("Verifications", {"To": destination, "Channel": channel})
        if result.get("status") != "pending":
            raise OTPProviderError("The verification request was not accepted.")

    def check(self, destination, code):
        if not code or len(code) > 12:
            return False
        result = self._post("VerificationCheck", {"To": destination, "Code": code})
        return result.get("status") == "approved" and result.get("valid") is True

    def _post(self, endpoint, values):
        token = base64.b64encode(f"{self.key_sid}:{self.key_secret}".encode("utf-8")).decode("ascii")
        request = Request(
            f"{self.API_ROOT}/{self.service_sid}/{endpoint}",
            data=urlencode(values).encode("ascii"),
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=8) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if endpoint == "VerificationCheck" and error.code == 404:
                return {"status": "expired", "valid": False}
            raise OTPProviderError("The verification service could not complete the request.") from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise OTPProviderError("The verification service could not complete the request.") from error
        if not isinstance(result, dict):
            raise OTPProviderError("The verification service returned an invalid response.")
        return result


def delivery_target(user, channel):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return user.email
    return re.sub(r"[^0-9+]", "", user.phone_number)


def start_otp(destination, channel, session, recipient_name="there"):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        GmailEmailOTP().start(destination, session, recipient_name)
        return
    TwilioVerify().start(destination, channel)


def check_otp(destination, channel, code, session):
    if channel == GmailEmailOTP.EMAIL_CHANNEL:
        return GmailEmailOTP().check(code, session)
    return TwilioVerify().check(destination, code)
