"""Tool request contracts. PLANNED: execution implemented in Phase 3.

These types describe the shape of a tool request as it moves through
policy and (later) execution. Policy owns the decision; this module owns
only the vocabulary both `policy/` and future `tools/` speak.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import DeviceId, EntityId


class ToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ToolExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class ToolRequest(VersionedModel):
    id: EntityId
    tool_name: str
    risk_level: ToolRiskLevel
    approval_state: ToolApprovalState = ToolApprovalState.PENDING
    execution_state: ToolExecutionState = ToolExecutionState.PENDING
    parameters: dict[str, Any] = {}
    origin_device_id: DeviceId
    requested_at: UtcDatetime
