"""Reminder contracts. PLANNED: scheduling/notification implemented in Phase 3."""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import DeviceId, EntityId


class ReminderStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    CANCELLED = "cancelled"


class Reminder(VersionedModel):
    id: EntityId
    title: str
    content: str | None = None
    due_at: UtcDatetime
    status: ReminderStatus = ReminderStatus.PENDING
    origin_device_id: DeviceId
    created_at: UtcDatetime
