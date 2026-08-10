"""Deterministic fake providers.

CI must never need real cloud credentials. These fakes let contract
tests exercise the Protocol shape without any vendor SDK or network
call. `FakeLLMProvider` is re-exported from `reva_core.models.fakes`
because, as of Phase 1A, it is also real runtime code (the documented
default provider `TypedInteractionService` uses — see that module's
docstring); everything else here remains test-only infrastructure.
"""

from __future__ import annotations

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.models.fakes import FakeLLMProvider
from reva_core.models.llm import LLMProvider, LLMRequest, LLMResponse
from reva_core.models.stt import STTProvider, STTRequest, STTResult
from reva_core.models.tts import TTSProvider, TTSRequest, TTSResult
from reva_core.shared.errors import ProviderError, ProviderErrorKind

__all__ = [
    "FakeLLMProvider",
    "FailingLLMProvider",
    "FakeEmbeddingProvider",
    "FakeSTTProvider",
    "FakeTTSProvider",
]


class FailingLLMProvider(LLMProvider):
    """Always raises a normalized ProviderError — never a vendor exception type."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise ProviderError(ProviderErrorKind.TIMEOUT, "fake provider timed out")


class FakeEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(vector=(0.1, 0.2, 0.3), correlation_id=request.correlation_id)


class FakeSTTProvider(STTProvider):
    async def transcribe(self, request: STTRequest) -> STTResult:
        return STTResult(
            transcript="fake transcript", confidence=0.99, correlation_id=request.correlation_id
        )


class FakeTTSProvider(TTSProvider):
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio=b"fake-audio-bytes", audio_format="wav", correlation_id=request.correlation_id
        )
