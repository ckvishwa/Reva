"""AuditEvent contract.

Construction itself enforces safety: a metadata dict containing a
sensitive key (see shared/redaction.py) raises instead of silently
redacting, so a caller finds out immediately rather than assuming the
value was captured.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import CorrelationId, DeviceId, EntityId
from reva_core.shared.redaction import redact_mapping


class AuditEventCategory(StrEnum):
    MEMORY = "memory"
    TOOL = "tool"
    POLICY = "policy"
    SYNC = "sync"
    PROVIDER = "provider"
    SYSTEM = "system"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


def _reject_sensitive_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if redact_mapping(value) != value:
        raise ValueError(
            "audit event metadata must not contain a sensitive key "
            "(api_key, password, token, etc.) — remove it before recording"
        )
    return value


SafeMetadata = Annotated[dict[str, Any], AfterValidator(_reject_sensitive_metadata)]


class AuditEvent(VersionedModel):
    id: EntityId
    category: AuditEventCategory
    action: str
    outcome: AuditOutcome
    correlation_id: CorrelationId | None = None
    actor_device_id: DeviceId | None = None
    metadata: SafeMetadata = {}
    occurred_at: UtcDatetime
