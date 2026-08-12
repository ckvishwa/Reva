from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from reva_core.shared.contracts.base import VersionedModel
from reva_core.shared.contracts.ids import CorrelationId

SUPPORTED_TTS_LANGUAGES = frozenset({"en", "te"})


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


class SynthesizedAudio(VersionedModel):
    """Core-controlled generated speech artifact.

    `path` points to a temporary file owned by Core, never to a client
    supplied path. Callers are responsible for deleting it after delivery
    or failure.
    """

    path: Path
    sample_rate: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    language: str = Field(pattern="^(en|te)$")
    provider: str


@runtime_checkable
class TextToSpeechProvider(Protocol):
    async def synthesize(self, text: str, language: str) -> SynthesizedAudio: ...
