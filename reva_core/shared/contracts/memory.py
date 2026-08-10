"""Memory contracts. PLANNED: capture/retrieval implemented starting Phase 1.

Vector/retrieval metadata is intentionally kept out of this module — a
`Memory` is authoritative source content; any future embedding lives in a
derived, rebuildable index that references a `Memory.id`, never the
other way around.
"""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import DeviceId, EntityId


class MemoryCategory(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    NOTE = "note"
    PROJECT_CONTEXT = "project_context"


class RetentionState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MemorySourceReference(VersionedModel):
    """Where a memory came from — required for source-aware recall (PRD 8.3)."""

    conversation_id: EntityId | None = None
    message_id: EntityId | None = None
    origin_device_id: DeviceId
    note: str | None = None


class Memory(VersionedModel):
    id: EntityId
    category: MemoryCategory
    content: str
    source: MemorySourceReference
    tags: tuple[str, ...] = ()
    retention_state: RetentionState = RetentionState.ACTIVE
    sync_version: int = 1
    created_at: UtcDatetime
    updated_at: UtcDatetime
