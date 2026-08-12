from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId

SUPPORTED_STT_LANGUAGES = frozenset({"en", "te"})


class STTRequest(VersionedModel):
    audio: bytes
    audio_format: str
    correlation_id: CorrelationId


class STTResult(VersionedModel):
    transcript: str
    confidence: float | None = None
    correlation_id: CorrelationId


class TranscriptionInput(VersionedModel):
    path: Path
    media_type: str


class TranscriptionResult(VersionedModel):
    text: str
    language: Literal["en", "te"]
    duration_ms: int
    provider: str


@runtime_checkable
class STTProvider(Protocol):
    async def transcribe(self, request: STTRequest) -> STTResult: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult: ...
