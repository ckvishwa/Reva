"""Phase 1A transport contracts.

Narrow request/response DTOs for the `/v1/*` endpoints. These are
deliberately separate from the domain contracts in
`shared/contracts/` — they describe what crosses the wire, not what
`memory/`-equivalent orchestration operates on internally. No raw
internal database row is ever returned directly.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, ConfigDict, Field

from reva_core.audit.events import AuditEvent
from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import CorrelationId, EntityId
from reva_core.shared.contracts.memory import MemoryCategory, MemorySourceReference

_MAX_MESSAGE_LENGTH = 4000
_MAX_MEMORY_CONTENT_LENGTH = 8000
_MAX_TAG_LENGTH = 64
_MAX_TAGS = 16


def _non_empty_stripped(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace-only")
    return stripped


NonEmptyStr = Annotated[str, AfterValidator(_non_empty_stripped)]


class ApiModel(VersionedModel):
    """Base for every wire contract in this module.

    Domain contracts (`shared/contracts/`) stay `strict=True` because
    they are built programmatically in Python. These are parsed from
    untrusted JSON over HTTP, where `strict=True` would reject entirely
    normal input — a JSON array can never satisfy a strict `tuple`
    field, and a JSON string can never satisfy a strict enum field —
    so this relaxes to pydantic's standard "lax" JSON coercion while
    keeping `extra="forbid"` and immutability from `VersionedModel`.
    """

    model_config = ConfigDict(strict=False)


class ErrorResponse(ApiModel):
    error: str
    correlation_id: CorrelationId | None = None


class TypedRequest(ApiModel):
    content: NonEmptyStr = Field(max_length=_MAX_MESSAGE_LENGTH)
    correlation_id: CorrelationId | None = None


class TypedResponse(ApiModel):
    correlation_id: CorrelationId
    reply: str
    memory_created: EntityId | None = None


class ExplicitMemoryCreateRequest(ApiModel):
    content: NonEmptyStr = Field(max_length=_MAX_MEMORY_CONTENT_LENGTH)
    category: MemoryCategory = MemoryCategory.NOTE
    tags: tuple[Annotated[str, Field(max_length=_MAX_TAG_LENGTH)], ...] = Field(
        default=(), max_length=_MAX_TAGS
    )
    correlation_id: CorrelationId | None = None


class ExplicitMemoryCreateResponse(ApiModel):
    id: EntityId
    category: MemoryCategory
    created_at: UtcDatetime
    correlation_id: CorrelationId


class MemoryQueryRequest(ApiModel):
    query: NonEmptyStr = Field(max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    correlation_id: CorrelationId | None = None


class MemoryQueryResponseItem(ApiModel):
    id: EntityId
    content: str
    category: MemoryCategory
    source: MemorySourceReference
    tags: tuple[str, ...]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MemoryQueryResponse(ApiModel):
    results: tuple[MemoryQueryResponseItem, ...]
    correlation_id: CorrelationId


class AuditEventListResponse(ApiModel):
    events: tuple[AuditEvent, ...]
    correlation_id: CorrelationId
