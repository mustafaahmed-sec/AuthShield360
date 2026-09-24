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
