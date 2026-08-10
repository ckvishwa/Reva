import pytest

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest
from reva_core.models.llm import LLMProvider, LLMRequest
from reva_core.models.stt import STTProvider, STTRequest
from reva_core.models.tts import TTSProvider, TTSRequest
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from tests.fixtures.fake_providers import (
    FailingLLMProvider,
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeSTTProvider,
    FakeTTSProvider,
)


def _correlation_id() -> str:
    import uuid

    return str(uuid.uuid4())


async def test_fake_llm_provider_satisfies_protocol():
    provider: LLMProvider = FakeLLMProvider()
    assert isinstance(provider, LLMProvider)
    response = await provider.complete(LLMRequest(prompt="hi", correlation_id=_correlation_id()))
    assert response.content == "Received: hi"


async def test_failing_llm_provider_raises_normalized_provider_error():
    provider: LLMProvider = FailingLLMProvider()
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete(LLMRequest(prompt="hi", correlation_id=_correlation_id()))
    assert excinfo.value.kind == ProviderErrorKind.TIMEOUT


async def test_fake_embedding_provider_satisfies_protocol():
    provider: EmbeddingProvider = FakeEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)
    result = await provider.embed(EmbeddingRequest(text="hi", correlation_id=_correlation_id()))
    assert len(result.vector) == 3


async def test_fake_stt_provider_satisfies_protocol():
    provider: STTProvider = FakeSTTProvider()
    assert isinstance(provider, STTProvider)
    result = await provider.transcribe(
        STTRequest(audio=b"raw-bytes", audio_format="wav", correlation_id=_correlation_id())
    )
    assert result.transcript


async def test_fake_tts_provider_satisfies_protocol():
    provider: TTSProvider = FakeTTSProvider()
    assert isinstance(provider, TTSProvider)
    result = await provider.synthesize(TTSRequest(text="hi", correlation_id=_correlation_id()))
    assert result.audio_format == "wav"
