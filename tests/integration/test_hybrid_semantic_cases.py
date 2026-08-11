# tests/integration/test_hybrid_semantic_cases.py
"""Proves docs/superpowers/plans WORK-ORDER section 4's required semantic
behaviors through TypedInteractionService.query_memories — the same path
GET /v1/memories uses. Deterministic embeddings (not real Ollama) keep
this fast and CI-safe; see the Plan 3 evaluation for real-model numbers."""

from __future__ import annotations

import pytest

from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository

_CID = "66666666-6666-6666-6666-666666666666"
_MODEL = "test-model"


class TopicEmbeddingProvider(EmbeddingProvider):
    """Assigns each known topic a distinct axis so cosine similarity
    reflects the intended semantic relationship deterministically."""

    _TOPICS = ["cat", "night", "sdet", "iphone", "maltrace", "recipe"]

    def _vector_for(self, text: str) -> tuple[float, ...]:
        lowered = text.lower()
        vector = [0.0] * len(self._TOPICS)
        matched = False
        for i, topic in enumerate(self._TOPICS):
            if topic in lowered:
                vector[i] = 1.0
                matched = True
        if not matched:
            vector = [0.05] * len(self._TOPICS)
        return tuple(vector)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            vector=self._vector_for(request.text), correlation_id=request.correlation_id
        )


@pytest.fixture
def service(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(
        conn,
        device_id,
        embedding_provider=TopicEmbeddingProvider(),
        embedding_model_id=_MODEL,
    )
    yield svc, conn, device_id
    conn.close()


async def _remember(service, content: str) -> None:
    svc, conn, _ = service
    memory = svc.create_explicit_memory(content, MemoryCategory.NOTE, (), _CID)
    from reva_core.memory.embedding_backfill import backfill_missing_embeddings

    await backfill_missing_embeddings(
        conn, TopicEmbeddingProvider(), model_id=_MODEL, correlation_id=_CID
    )
    return memory


async def test_case_1_pet_cat(service):
    await _remember(service, "I have a pet cat.")
    svc, _, _ = service

    results = await svc.query_memories("What animal do I own?", 5, _CID)

    assert results and "cat" in results[0].content.lower()


async def test_case_2_works_late_at_night(service):
    await _remember(service, "I prefer working late at night.")
    svc, _, _ = service

    results = await svc.query_memories("When do I usually like doing focused work?", 5, _CID)

    assert results and "night" in results[0].content.lower()


async def test_case_3_sdet_career_target(service):
    await _remember(service, "My main career target is SDET.")
    svc, _, _ = service

    results = await svc.query_memories("What kind of testing job am I targeting?", 5, _CID)

    assert results and "sdet" in results[0].content.lower()


async def test_case_4_iphone_daily_driver(service):
    await _remember(service, "I use an iPhone 12 as my main phone.")
    svc, _, _ = service

    results = await svc.query_memories("Which handset is my daily driver?", 5, _CID)

    assert results and "iphone" in results[0].content.lower()


async def test_case_5_maltrace_project(service):
    await _remember(service, "I built MalTrace to analyze malware behavior.")
    svc, _, _ = service

    results = await svc.query_memories("Which project did I make for malware analysis?", 5, _CID)

    assert results and "maltrace" in results[0].content.lower()


async def test_negative_case_no_confident_match(service):
    await _remember(service, "I have a pet cat.")
    await _remember(service, "My main career target is SDET.")
    svc, _, _ = service

    results = await svc.query_memories("best recipe for banana bread", 5, _CID)

    assert not any("cat" in r.content.lower() or "sdet" in r.content.lower() for r in results)
