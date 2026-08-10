from __future__ import annotations

from typing import Protocol, runtime_checkable

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId


class LLMRequest(VersionedModel):
    prompt: str
    correlation_id: CorrelationId


class LLMResponse(VersionedModel):
    content: str
    correlation_id: CorrelationId


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
