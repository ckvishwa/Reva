"""B4: the embedding provider is the real local one, with lexical search as the fallback.

A fake provider that quietly stood in for the real one would make every semantic result look
fine while meaning nothing. The checks: the provider the Core builds is Ollama, no fake embedding
class exists in the shipped code, and when the backend is down a search still answers lexically.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.shared.ids import new_id

ROOT = Path(__file__).resolve().parents[2]


def test_the_core_builds_the_ollama_provider_not_a_stand_in(core) -> None:
    provider = core.embedding_provider

    assert isinstance(provider, OllamaEmbeddingProvider)
    assert core.embedding_model_id == core.settings.embedding_model == "nomic-embed-text"


def test_no_fake_embedding_class_exists_in_the_shipped_package() -> None:
    offenders = []
    for path in (ROOT / "reva_core").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name = node.name.lower() if isinstance(node, ast.ClassDef) else ""
            if "embed" in name and any(w in name for w in ("fake", "stub", "mock", "dummy")):
                offenders.append(f"{path.name}:{node.name}")

    assert offenders == []


def test_an_unreachable_backend_is_a_typed_error_the_search_can_fall_back_on() -> None:
    import httpx

    from reva_core.models.embedding import EmbeddingRequest

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    provider = OllamaEmbeddingProvider(
        model="nomic-embed-text",
        api_base="http://127.0.0.1:1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )

    try:
        asyncio.run(provider.embed(EmbeddingRequest(text="hello", correlation_id=new_id())))
    except ProviderError as error:
        assert error.kind == ProviderErrorKind.UNAVAILABLE
    else:
        raise AssertionError("an unreachable backend must raise ProviderError")
