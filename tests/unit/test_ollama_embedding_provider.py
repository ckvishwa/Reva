"""OllamaEmbeddingProvider: local-first embedding backend, no cloud
credential. Uses httpx.MockTransport — no real Ollama server required
for this test; a real-Ollama integration path is exercised only by
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md's evaluation,
which is explicitly not part of CI."""

from __future__ import annotations

import httpx
import pytest

from reva_core.models.embedding import EmbeddingRequest
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.errors import ProviderError, ProviderErrorKind

_CID = "44444444-4444-4444-4444-444444444444"


def _client_with_transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_embed_returns_vector_from_ollama_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embeddings"
        body = request.read()
        assert b"nomic-embed-text" in body
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    result = await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert result.vector == pytest.approx((0.1, 0.2, 0.3))
    assert result.correlation_id == _CID


async def test_embed_raises_provider_error_on_connection_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE


async def test_embed_raises_provider_error_on_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not found"})

    provider = OllamaEmbeddingProvider(
        model="missing-model",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_embed_raises_provider_error_on_malformed_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_embed_raises_provider_error_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:11434",
        client=_client_with_transport(handler),
    )

    with pytest.raises(ProviderError) as excinfo:
        await provider.embed(EmbeddingRequest(text="hello", correlation_id=_CID))

    assert excinfo.value.kind == ProviderErrorKind.TIMEOUT
