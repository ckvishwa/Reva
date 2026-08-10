"""SyncEvent contract. PLANNED: transport and reconciliation implemented in Phase 5."""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import DeviceId, EntityId


class SyncEntityType(StrEnum):
    CONVERSATION = "conversation"
    MESSAGE = "message"
    MEMORY = "memory"
    REMINDER = "reminder"
    PERMISSION = "permission"


class SyncOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class SyncEvent(VersionedModel):
    id: EntityId
    device_id: DeviceId
    entity_type: SyncEntityType
    entity_id: EntityId
    entity_version: int
    operation: SyncOperation
    occurred_at: UtcDatetime
