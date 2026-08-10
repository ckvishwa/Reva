"""ID type conventions used across every contract.

- EntityId / DeviceId: UUIDv7 string. Identity for anything durable or
  cross-device. Never a database auto-increment integer.
- CorrelationId: any valid UUID string. Used to trace a single request
  across logs and audit events; does not need to be time-sortable.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import AfterValidator

from reva_core.shared.ids import is_uuid7


def _validate_entity_id(value: str) -> str:
    if not is_uuid7(value):
        raise ValueError(f"expected a UUIDv7 string, got {value!r}")
    return value


def _validate_correlation_id(value: str) -> str:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"expected a UUID string, got {value!r}") from exc
    return value


EntityId = Annotated[str, AfterValidator(_validate_entity_id)]
DeviceId = Annotated[str, AfterValidator(_validate_entity_id)]
CorrelationId = Annotated[str, AfterValidator(_validate_correlation_id)]
