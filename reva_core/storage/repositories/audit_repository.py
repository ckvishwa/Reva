"""Persistence for `audit_events`.

The only repository implemented in Phase 0 — audit is a cross-cutting
concern (see docs/architecture/module-boundaries.md), not a Phase 1+
product feature, so it exists now to prove the full contract -> storage
round trip actually works, not just in isolation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from reva_core.audit.events import AuditEvent, AuditEventCategory, AuditOutcome
from reva_core.shared.errors import StorageError


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, event: AuditEvent) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO audit_events
                    (id, category, action, outcome, correlation_id,
                     actor_device_id, metadata, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.category.value,
                    event.action,
                    event.outcome.value,
                    event.correlation_id,
                    event.actor_device_id,
                    json.dumps(event.metadata),
                    event.occurred_at.isoformat(),
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to insert audit event {event.id}: {exc}") from exc

    def list_recent(self, limit: int = 50) -> list[AuditEvent]:
        rows = self._conn.execute(
            "SELECT * FROM audit_events ORDER BY occurred_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            category=AuditEventCategory(row["category"]),
            action=row["action"],
            outcome=AuditOutcome(row["outcome"]),
            correlation_id=row["correlation_id"],
            actor_device_id=row["actor_device_id"],
            metadata=json.loads(row["metadata"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )
