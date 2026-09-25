"""Write structured audit events without storing credentials or raw session keys."""

import hashlib
import ipaddress
import logging

from django.conf import settings

from .models import PortalAuditEvent


logger = logging.getLogger("authshield.audit")

FAILURE_ACTIONS = {
    "login_failure",
    "otp_failure",
    "registration_status_failure",
    "locked_out",
    "ip_rate_limited",
    "role_access_denied",
}


def request_ip(request):
    """Return the peer IP observed by Django; forwarded headers are not trusted here."""
    raw_address = request.META.get("REMOTE_ADDR", "") if request else ""
    try:
        return str(ipaddress.ip_address(raw_address))
    except ValueError:
        return None


def _session_hint(request):
    session_key = request.session.session_key if request else None
    if not session_key:
        return ""
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:8]


def _auth_mode(auth_mode=None):
    mode = auth_mode or getattr(settings, "AUTHSHIELD_AUTH_MODE", "password")
    return mode if mode in PortalAuditEvent.AuthMode.values else PortalAuditEvent.AuthMode.PASSWORD


def _factor_for_action(action):
    if action.startswith("login_") or action.startswith("registration_status_"):
        return PortalAuditEvent.Factor.PASSWORD
    if action.startswith("logout_"):
        return PortalAuditEvent.Factor.SESSION
    return PortalAuditEvent.Factor.ACCESS


def _outcome_for_action(action):
    if action in FAILURE_ACTIONS or action.endswith("_failure") or action.endswith("_denied"):
        return PortalAuditEvent.Outcome.FAILURE
    return PortalAuditEvent.Outcome.SUCCESS


def _event_metadata(request, action, factor=None, outcome=None, auth_mode=None, duration_ms=None):
    return {
        "auth_mode": _auth_mode(auth_mode),
        "factor": factor or _factor_for_action(action),
        "outcome": outcome or _outcome_for_action(action),
        "ip_address": request_ip(request),
        "session_hint": _session_hint(request),
        "duration_ms": max(0, int(duration_ms)) if duration_ms is not None else None,
    }


def record_event(
    actor,
    action,
    description,
    target_name="",
    *,
    request=None,
    factor=None,
    outcome=None,
    auth_mode=None,
    duration_ms=None,
):
    if not actor or not actor.is_authenticated:
        return None
    event = PortalAuditEvent.objects.create(
        actor=actor,
        actor_name=actor.full_name,
        actor_email=actor.email,
        actor_role=actor.role,
        action=action,
        target_name=target_name,
        description=description[:300],
        **_event_metadata(request, action, factor, outcome, auth_mode, duration_ms),
    )
    logger.info("event=%s actor_id=%s event_id=%s", action, actor.pk, event.pk)
    return event


def record_auth_event(
    action,
    email="",
    actor=None,
    description="",
    *,
    request=None,
    factor=None,
    outcome=None,
    auth_mode=None,
    duration_ms=None,
):
    """Record an authentication event, including attempts without an actor."""
    if actor and actor.is_authenticated:
        return record_event(
            actor,
            action,
            description or action.replace("_", " "),
            target_name=email,
            request=request,
            factor=factor,
            outcome=outcome,
            auth_mode=auth_mode,
            duration_ms=duration_ms,
        )
    event = PortalAuditEvent.objects.create(
        actor=None,
        actor_name="Unauthenticated user",
        actor_email=(email or "unknown@example.test")[:254],
        actor_role="unknown",
        action=action,
        target_name="",
        description=(description or action.replace("_", " "))[:300],
        **_event_metadata(request, action, factor, outcome, auth_mode, duration_ms),
    )
    logger.info("event=%s actor_id=anonymous event_id=%s", action, event.pk)
    return event


def record_role_denial(actor, resource, request=None):
    if actor and actor.is_authenticated:
        if request is not None:
            recorded = getattr(request, "_authshield_recorded_role_denials", set())
            if resource in recorded:
                return None
            recorded.add(resource)
            request._authshield_recorded_role_denials = recorded
        record_event(
            actor,
            "role_access_denied",
            f"Denied access to the {resource} resource.",
            target_name=resource,
            request=request,
            factor=PortalAuditEvent.Factor.ACCESS,
            outcome=PortalAuditEvent.Outcome.FAILURE,
        )
