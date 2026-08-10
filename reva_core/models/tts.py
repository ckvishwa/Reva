from __future__ import annotations

from typing import Protocol, runtime_checkable

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId


class TTSRequest(VersionedModel):
    text: str
    correlation_id: CorrelationId


class TTSResult(VersionedModel):
    audio: bytes
    audio_format: str
    correlation_id: CorrelationId


@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResult: ...
