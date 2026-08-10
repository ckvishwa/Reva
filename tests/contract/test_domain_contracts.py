"""Contract tests: every domain contract round-trips through JSON, carries
schema_version, and rejects naive datetimes."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from reva_core.shared.contracts.conversation import Conversation, Message, MessageRole
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.contracts.permission import Permission, PermissionCapability
from reva_core.shared.contracts.reminder import Reminder, ReminderStatus
from reva_core.shared.contracts.sync import SyncEntityType, SyncEvent, SyncOperation
from reva_core.shared.contracts.tool import (
    ToolApprovalState,
    ToolExecutionState,
    ToolRequest,
    ToolRiskLevel,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now


def _round_trip(model):
    cls = type(model)
    restored = cls.model_validate_json(model.model_dump_json())
    assert restored == model
    assert restored.schema_version == 1


def test_message_round_trip():
    message = Message(
        id=new_id(),
        conversation_id=new_id(),
        role=MessageRole.USER,
        content="hello",
        origin_device_id=new_id(),
        created_at=utc_now(),
    )
    _round_trip(message)


def test_conversation_round_trip():
    now = utc_now()
    conversation = Conversation(
        id=new_id(),
        title="Vision doc",
        origin_device_id=new_id(),
        created_at=now,
        updated_at=now,
    )
    _round_trip(conversation)


def test_memory_round_trip_with_source_reference():
    now = utc_now()
    memory = Memory(
        id=new_id(),
        category=MemoryCategory.DECISION,
        content="V1 uses push-to-talk, not always-on listening.",
        source=MemorySourceReference(origin_device_id=new_id(), note="typed chat"),
        tags=("voice", "v1"),
        retention_state=RetentionState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    _round_trip(memory)


def test_reminder_round_trip():
    reminder = Reminder(
        id=new_id(),
        title="Write the Vision section",
        due_at=utc_now(),
        status=ReminderStatus.PENDING,
        origin_device_id=new_id(),
        created_at=utc_now(),
    )
    _round_trip(reminder)


def test_tool_request_round_trip():
    tool_request = ToolRequest(
        id=new_id(),
        tool_name="open_url",
        risk_level=ToolRiskLevel.LOW,
        approval_state=ToolApprovalState.PENDING,
        execution_state=ToolExecutionState.PENDING,
        parameters={"url": "https://example.com"},
        origin_device_id=new_id(),
        requested_at=utc_now(),
    )
    _round_trip(tool_request)


def test_permission_round_trip():
    permission = Permission(
        id=new_id(),
        capability=PermissionCapability.MICROPHONE,
        granted=False,
        updated_at=utc_now(),
    )
    _round_trip(permission)


def test_sync_event_round_trip():
    sync_event = SyncEvent(
        id=new_id(),
        device_id=new_id(),
        entity_type=SyncEntityType.MEMORY,
        entity_id=new_id(),
        entity_version=1,
        operation=SyncOperation.CREATE,
        occurred_at=utc_now(),
    )
    _round_trip(sync_event)


def test_message_role_enum_has_all_prd_roles():
    assert {r.value for r in MessageRole} == {"user", "assistant", "system", "tool"}


def test_naive_datetime_rejected_in_domain_contract():
    from datetime import datetime

    with pytest.raises(PydanticValidationError):
        Reminder(
            id=new_id(),
            title="x",
            due_at=datetime(2026, 1, 1),
            origin_device_id=new_id(),
            created_at=utc_now(),
        )


def test_tool_request_rejects_unknown_risk_level():
    with pytest.raises(PydanticValidationError):
        ToolRequest(
            id=new_id(),
            tool_name="open_url",
            risk_level="critical",
            origin_device_id=new_id(),
            requested_at=utc_now(),
        )
