"""Small immutable event records for account and student-record changes."""

from .models import PortalAuditEvent


def record_event(actor, action, description, target_name=""):
    if not actor or not actor.is_authenticated:
        return None
    return PortalAuditEvent.objects.create(
        actor=actor,
        actor_name=actor.full_name,
        actor_email=actor.email,
        actor_role=actor.role,
        action=action,
        target_name=target_name,
        description=description[:300],
    )


def record_auth_event(action, email="", actor=None, description=""):
    """Record an authentication event, including attempts without an actor."""
    if actor and actor.is_authenticated:
        return record_event(actor, action, description or action.replace("_", " "), target_name=email)
    return PortalAuditEvent.objects.create(
        actor=None,
        actor_name="Unauthenticated user",
        actor_email=(email or "unknown@example.test")[:254],
        actor_role="unknown",
        action=action,
        target_name="",
        description=(description or action.replace("_", " "))[:300],
    )


def record_role_denial(actor, resource):
    if actor and actor.is_authenticated:
        record_event(
            actor,
            "role_access_denied",
            f"Denied access to the {resource} resource.",
            target_name=resource,
        )
