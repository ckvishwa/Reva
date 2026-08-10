"""Resolve a request's correlation ID: accept a valid caller-provided
value (`X-Correlation-Id` header, or the request body's own
`correlation_id` field, checked by callers in that priority order),
or generate a fresh one. Every audit event for a request carries this
ID so a single interaction can be traced across the audit trail."""

from __future__ import annotations

import uuid


def resolve_correlation_id(raw: str | None) -> str:
    if raw:
        try:
            uuid.UUID(raw)
            return raw
        except ValueError:
            pass
    return str(uuid.uuid4())
