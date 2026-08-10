"""HealthStatus contract — shared between orchestration (produces it) and
api (serializes it). Not a durable record; still versioned for the same
reason any cross-boundary contract is."""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel


class CoreStatus(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


class HealthStatus(VersionedModel):
    status: CoreStatus
    db_schema_version: int
    started_at: UtcDatetime | None = None
