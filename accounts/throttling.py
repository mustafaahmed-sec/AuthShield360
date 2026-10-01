"""Shared privacy-preserving request quotas backed by the application database."""

from datetime import timedelta
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PublicRequestThrottle


def consume_throttle_quota(*, scope, purpose, identity, limit, window_minutes, now=None):
    """Consume a quota without storing the source identity in readable form."""
    fingerprint = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{scope}:{purpose}:{identity}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    now = now or timezone.now()
    window = timedelta(minutes=window_minutes)

    with transaction.atomic():
        bucket, created = PublicRequestThrottle.objects.select_for_update().get_or_create(
            purpose=purpose[:32],
            fingerprint=fingerprint,
            defaults={"window_started_at": now, "request_count": 1},
        )
        if not created:
            if now - bucket.window_started_at >= window:
                bucket.window_started_at = now
                bucket.request_count = 0
            if bucket.request_count >= limit:
                return False
            bucket.request_count += 1
            bucket.save(update_fields=("window_started_at", "request_count"))

        # Quota keys contain no raw identity and old windows have no ongoing use.
        PublicRequestThrottle.objects.filter(
            window_started_at__lt=now - max(window, timedelta(days=2))
        ).delete()
    return True
