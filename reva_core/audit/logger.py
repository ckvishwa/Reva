"""Emit an AuditEvent to structured logs (defense-in-depth alongside
storage persistence — `shared.logging` redacts independently, so a
sensitive value would be caught twice, not once)."""

from __future__ import annotations

from reva_core.audit.events import AuditEvent
from reva_core.shared.logging import get_logger

_logger = get_logger("audit")


def log_audit_event(event: AuditEvent) -> None:
    _logger.info(
        event.action,
        extra={
            "audit_id": event.id,
            "category": event.category.value,
            "outcome": event.outcome.value,
            "correlation_id": event.correlation_id,
            **event.metadata,
        },
    )
