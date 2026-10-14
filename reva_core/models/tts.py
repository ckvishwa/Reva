from __future__ import annotations

from collections.abc import AsyncIterator
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


class SpeechChunk(VersionedModel):
    """One sentence-sized piece of synthesized speech (chunked, not streaming).

    `turn_epoch` is the epoch the speech was requested under. A consumer
    drops any chunk whose epoch is older than the session's current epoch
    (AR-VA-004). `path` is a Core-owned temp file; the consumer deletes it.
    """

    turn_epoch: int = Field(ge=0)
    index: int = Field(ge=0)
    path: Path
    sample_rate: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    final: bool
    language: str = Field(pattern="^(en|te)$")
    provider: str


class ProviderHealth(VersionedModel):
    ok: bool
    detail: str
    voice: str | None = None
    pid: int | None = None


@runtime_checkable
class SpeechProvider(Protocol):
    """speak / stop / health, the shared TTS provider protocol (AR-VA-008)."""

    name: str

    async def health(self) -> ProviderHealth: ...

    def speak(
        self, text: str, *, language: str, turn_epoch: int, scope: str = ""
    ) -> AsyncIterator[SpeechChunk]: ...

    async def stop(self, *, turn_epoch: int, scope: str = "") -> None: ...

    async def shutdown(self) -> None: ...
