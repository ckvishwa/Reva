"""Real EmbeddingProvider implementations.

OllamaEmbeddingProvider is the local-first default: same Ollama server
REVA already requires for ADK chat (ollama_chat/llama3.1:8b), reached
via its /api/embeddings HTTP endpoint. No new heavy dependency (no
torch/sentence-transformers) — an embedding model like nomic-embed-text
is a small (~270MB) CPU-friendly Ollama pull, appropriate for the
4GB-VRAM local hardware this runs on.

Vendor exceptions never leak past this module (see
reva_core/shared/errors.py's module docstring) — every httpx failure
mode is normalized into ProviderError with an explicit kind.
"""

from __future__ import annotations

import httpx

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.errors import ProviderError, ProviderErrorKind

_EMBEDDINGS_PATH = "/api/embeddings"


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                f"{self._api_base}{_EMBEDDINGS_PATH}",
                json={"model": self._model, "prompt": request.text},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, "Embedding request timed out."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "Embedding backend is unreachable."
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

        if response.status_code != 200:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                f"Embedding backend returned status {response.status_code}.",
            )

        try:
            payload = response.json()
            vector = payload["embedding"]
            if not isinstance(vector, list) or not vector:
                raise ValueError("empty or non-list embedding")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE,
                "Embedding backend returned an unparseable response.",
            ) from exc

        vector_tuple = tuple(float(v) for v in vector)
        return EmbeddingResult(
            vector=vector_tuple, correlation_id=request.correlation_id
        )
