# tests/unit/test_hybrid_retrieval.py
"""Hybrid ranking: lexical LIKE candidates + semantic cosine candidates,
normalized to [0,1], combined with centralized weights, minimum-confidence
filtered, deterministically tie-broken. Uses a deterministic
DeterministicEmbeddingProvider (below) instead of real Ollama — the real
model's semantic behavior is proven in
tests/integration/test_hybrid_semantic_cases.py (Task 7) and the
Ollama-backed evaluation in docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md.
"""

from __future__ import annotations

import pytest

from reva_core.memory.hybrid_retrieval import cosine_similarity, hybrid_search
from reva_core.memory.ranking import HybridRankingConfig
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.contracts.memory import Memory, MemoryCategory, MemorySourceReference, RetentionState
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "33333333-3333-3333-3333-333333333333"
_MODEL = "test-model"


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Maps known text substrings to hand-picked vectors so semantic
    relationships are provable without a real embedding model."""

    def __init__(self, vectors_by_keyword: dict[str, tuple[float, ...]], default: tuple[float, ...]) -> None:
        self._vectors_by_keyword = vectors_by_keyword
        self._default = default

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        lowered = request.text.lower()
        for keyword, vector in self._vectors_by_keyword.items():
            if keyword in lowered:
                return EmbeddingResult(vector=vector, correlation_id=request.correlation_id)
        return EmbeddingResult(vector=self._default, correlation_id=request.correlation_id)


class FailingEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise RuntimeError("embedding backend unreachable")


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    yield conn
    conn.close()


def _insert_memory(conn, content: str) -> Memory:
    now = utc_now()
    device_id = new_id()
    # Create the device that will be referenced by the memory's origin_device_id
    # (memories.origin_device_id has a NOT NULL FOREIGN KEY REFERENCES devices(id)).
    conn.execute(
        "INSERT INTO devices (id, display_name, platform, paired_at) VALUES (?, ?, ?, ?)",
        (device_id, "Test Device", "test", now.isoformat()),
    )
    memory = Memory(
        id=new_id(),
        category=MemoryCategory.NOTE,
        content=content,
        source=MemorySourceReference(origin_device_id=device_id, note="test"),
        tags=(),
        retention_state=RetentionState.ACTIVE,
        sync_version=1,
        created_at=now,
        updated_at=now,
    )
    MemoryRepository(conn).insert(memory)
    return memory


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_negative_one():
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_is_zero_not_nan():
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0


async def test_semantic_match_ranks_first_with_no_keyword_overlap(store):
    cat_memory = _insert_memory(store, "I have a pet cat.")
    _insert_memory(store, "unrelated distractor about databases")
    embeddings = MemoryEmbeddingRepository(store)
    provider = DeterministicEmbeddingProvider(
        vectors_by_keyword={"cat": (1.0, 0.0), "animal": (1.0, 0.0), "database": (0.0, 1.0)},
        default=(0.0, 0.5),
    )
    for content, memory in [("I have a pet cat.", cat_memory)]:
        embeddings.upsert(memory.id, _MODEL, (1.0, 0.0))

    results = await hybrid_search(
        store, provider, query="What animal do I own?", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert results
    assert results[0].memory.id == cat_memory.id


async def test_lexical_exact_match_still_surfaces(store):
    memory = _insert_memory(store, "REVA uses Push-To-Talk")
    embeddings = MemoryEmbeddingRepository(store)
    embeddings.upsert(memory.id, _MODEL, (0.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 1.0))

    results = await hybrid_search(
        store, provider, query="push-to-talk", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert any(r.memory.id == memory.id for r in results)


async def test_below_minimum_confidence_excluded(store):
    _insert_memory(store, "completely unrelated content about spreadsheets")
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))
    config = HybridRankingConfig(semantic_weight=0.70, lexical_weight=0.30, minimum_confidence=0.99)

    results = await hybrid_search(
        store, provider, query="banana bread recipe", limit=5, model_id=_MODEL,
        correlation_id=_CID, config=config,
    )

    assert results == []


async def test_tie_break_is_deterministic_across_repeated_calls(store):
    first = _insert_memory(store, "tie candidate alpha")
    second = _insert_memory(store, "tie candidate beta")
    embeddings = MemoryEmbeddingRepository(store)
    embeddings.upsert(first.id, _MODEL, (1.0, 0.0))
    embeddings.upsert(second.id, _MODEL, (1.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))

    results_a = await hybrid_search(store, provider, query="tie candidate", limit=5, model_id=_MODEL, correlation_id=_CID)
    results_b = await hybrid_search(store, provider, query="tie candidate", limit=5, model_id=_MODEL, correlation_id=_CID)

    assert [r.memory.id for r in results_a] == [r.memory.id for r in results_b]


async def test_embedding_provider_failure_falls_back_to_lexical_only(store):
    memory = _insert_memory(store, "fallback lexical match content")
    provider = FailingEmbeddingProvider()

    results = await hybrid_search(
        store, provider, query="fallback lexical match", limit=5, model_id=_MODEL, correlation_id=_CID
    )

    assert any(r.memory.id == memory.id for r in results)


async def test_none_embedding_provider_uses_lexical_only(store):
    memory = _insert_memory(store, "no provider configured content")

    results = await hybrid_search(store, None, query="no provider configured", limit=5, model_id=_MODEL, correlation_id=_CID)

    assert any(r.memory.id == memory.id for r in results)


async def test_limit_is_respected(store):
    for i in range(10):
        m = _insert_memory(store, f"bounded candidate {i}")
        MemoryEmbeddingRepository(store).upsert(m.id, _MODEL, (1.0, 0.0))
    provider = DeterministicEmbeddingProvider(vectors_by_keyword={}, default=(1.0, 0.0))

    results = await hybrid_search(store, provider, query="bounded candidate", limit=3, model_id=_MODEL, correlation_id=_CID)

    assert len(results) <= 3
