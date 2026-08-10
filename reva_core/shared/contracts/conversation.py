"""Conversation and Message contracts. PLANNED: populated starting Phase 1."""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import DeviceId, EntityId


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(VersionedModel):
    id: EntityId
    conversation_id: EntityId
    role: MessageRole
    content: str
    origin_device_id: DeviceId
    created_at: UtcDatetime


class Conversation(VersionedModel):
    id: EntityId
    title: str
    origin_device_id: DeviceId
    created_at: UtcDatetime
    updated_at: UtcDatetime
