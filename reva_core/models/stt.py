from __future__ import annotations

from typing import Protocol, runtime_checkable

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId


class STTRequest(VersionedModel):
    audio: bytes
    audio_format: str
    correlation_id: CorrelationId


class STTResult(VersionedModel):
    transcript: str
    confidence: float | None = None
    correlation_id: CorrelationId


@runtime_checkable
class STTProvider(Protocol):
    async def transcribe(self, request: STTRequest) -> STTResult: ...
