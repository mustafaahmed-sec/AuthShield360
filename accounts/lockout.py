"""Small, database-backed throttles for the password-only demonstration."""

from datetime import timedelta
from math import ceil

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.models import User
from school.audit import record_auth_event, request_ip
from school.models import PortalAuditEvent


FAILURE_ACTIONS = ("login_failure", "registration_status_failure", "otp_failure", "password_reset_failure")
SUCCESS_ACTIONS = ("login_success", "registration_status_success", "password_reset_completed")


def normalized_email(value):
    return (value or "").strip().lower()[:254]


def retry_minutes(until, now=None):
    now = now or timezone.now()
    seconds = max(0, (until - now).total_seconds())
    return max(1, ceil(seconds / 60))


def account_lockout_until(email, now=None):
    email = normalized_email(email)
    if not email:
        return None
    now = now or timezone.now()
    user = User.objects.filter(email__iexact=email).only("locked_until").first()
    if user and user.locked_until and user.locked_until > now:
        return user.locked_until
    return None


def ip_throttle_until(request, now=None):
    address = request_ip(request)
    limit = settings.AUTHSHIELD_IP_FAILURE_LIMIT
    if not address or limit <= 0:
        return None

    now = now or timezone.now()
    window_start = now - timedelta(minutes=settings.AUTHSHIELD_IP_WINDOW_MINUTES)
    failures = PortalAuditEvent.objects.filter(
        ip_address=address,
        action__in=FAILURE_ACTIONS,
        created_at__gte=window_start,
    )
    if failures.count() < limit:
        return None

    last_failure = failures.order_by("-created_at", "-pk").first()
    until = last_failure.created_at + timedelta(minutes=settings.AUTHSHIELD_IP_THROTTLE_MINUTES)
    return until if until > now else None


def _failure_count_for_account(email, now):
    email = normalized_email(email)
    window_start = now - timedelta(minutes=settings.AUTHSHIELD_LOCKOUT_WINDOW_MINUTES)
    failures = PortalAuditEvent.objects.filter(
        actor_email__iexact=email,
        action__in=FAILURE_ACTIONS,
        created_at__gte=window_start,
    )
    reset_events = PortalAuditEvent.objects.filter(created_at__gte=window_start).filter(
        Q(actor_email__iexact=email, action__in=SUCCESS_ACTIONS)
        | Q(action="account_unlocked", target_name__iexact=email)
    )
    reset_at = reset_events.aggregate(latest=Max("created_at"))["latest"]
    if reset_at:
        failures = failures.filter(created_at__gt=reset_at)
    return failures.count()


def record_failed_authentication(email, action, request, duration_ms=None, factor="password", description=None):
    """Log a failed attempt and start a temporary lock after the configured threshold."""
    email = normalized_email(email)
    now = timezone.now()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email__iexact=email).first() if email else None
        record_auth_event(
            action,
            email=email,
            description=description or (
                "Failed one-time-code verification." if action == "otp_failure" else "Failed password authentication."
            ),
            request=request,
            factor=factor,
            outcome="failure",
            duration_ms=duration_ms,
        )

        if not user or _failure_count_for_account(email, now) < settings.AUTHSHIELD_LOCKOUT_ATTEMPTS:
            return None

        locked_until = now + timedelta(minutes=settings.AUTHSHIELD_LOCKOUT_MINUTES)
        User.objects.filter(pk=user.pk).update(locked_until=locked_until)
        record_auth_event(
            "locked_out",
            email=email,
            description="Temporary account lock activated after repeated failed attempts.",
            request=request,
            factor=factor,
            outcome="failure",
            duration_ms=duration_ms,
        )
        return locked_until


def record_blocked_attempt(email, request, *, action="locked_out", duration_ms=None):
    record_auth_event(
        action,
        email=normalized_email(email),
        description=(
            "Authentication blocked by the temporary account lock."
            if action == "locked_out"
            else "Authentication temporarily throttled for this request source."
        ),
        request=request,
        factor="password",
        outcome="failure",
        duration_ms=duration_ms,
    )


def clear_expired_or_successful_lock(user):
    if user and user.locked_until:
        User.objects.filter(pk=user.pk).update(locked_until=None)
