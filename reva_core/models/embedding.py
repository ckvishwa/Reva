from __future__ import annotations

from typing import Protocol, runtime_checkable

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId


class EmbeddingRequest(VersionedModel):
    text: str
    correlation_id: CorrelationId


class EmbeddingResult(VersionedModel):
    vector: tuple[float, ...]
    correlation_id: CorrelationId


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...
