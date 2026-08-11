"""Proves docs/superpowers/plans WORK-ORDER section 4's required semantic
behaviors through TypedInteractionService.query_memories — the same path
GET /v1/memories uses. Deterministic embeddings (not real Ollama) keep
this fast and CI-safe; see the Plan 3 evaluation for real-model numbers."""

from __future__ import annotations

import pytest

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import Memory, MemoryCategory
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository

_CID = "66666666-6666-6666-6666-666666666666"
_MODEL = "test-model"


class TopicEmbeddingProvider(EmbeddingProvider):
    """Assigns each known topic a distinct axis so cosine similarity
    reflects the intended semantic relationship deterministically.

    `_SYNONYMS` recognizes a handful of related terms per topic (e.g.
    "animal"/"pet" for "cat") so a natural-language query — deliberately
    worded to avoid the target memory's exact phrasing — still routes to
    the correct topic axis. A real embedding model learns this kind of
    relationship from data; this deterministic stub hard-codes the same
    effect via table lookup so tests stay fast and CI-safe.
    """

    _TOPICS = ["cat", "night", "sdet", "iphone", "maltrace", "recipe"]
    _SYNONYMS: dict[str, tuple[str, ...]] = {
        "cat": ("cat", "animal", "pet"),
        "night": ("night", "late", "evening"),
        "sdet": ("sdet", "testing", "tester"),
        "iphone": ("iphone", "phone", "handset"),
        "maltrace": ("maltrace", "malware"),
        "recipe": ("recipe", "cooking"),
    }

    def _vector_for(self, text: str) -> tuple[float, ...]:
        lowered = text.lower()
        vector = [0.0] * len(self._TOPICS)
        matched = False
        for i, topic in enumerate(self._TOPICS):
            if any(term in lowered for term in self._SYNONYMS[topic]):
                vector[i] = 1.0
                matched = True
        if not matched:
            vector = [0.05] * len(self._TOPICS)
        return tuple(vector)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(
            vector=self._vector_for(request.text), correlation_id=request.correlation_id
        )


# One representative memory per topic, reused both as each case's target
# and as other cases' distractors — every sentence embeds to a clean
# one-hot vector on its own topic axis (verified: no cross-topic synonym
# collisions among these six sentences).
_TOPIC_CONTENT: dict[str, str] = {
    "cat": "I have a pet cat.",
    "night": "I prefer working late at night.",
    "sdet": "My main career target is SDET.",
    "iphone": "I use an iPhone 12 as my main phone.",
    "maltrace": "I built MalTrace to analyze malware behavior.",
    "recipe": "My favorite recipe is banana bread with walnuts.",
}


@pytest.fixture
def service(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    provider = TopicEmbeddingProvider()
    svc = TypedInteractionService(
        conn,
        device_id,
        embedding_provider=provider,
        embedding_model_id=_MODEL,
    )
    yield svc, conn, device_id, provider
    conn.close()


async def _remember(service, content: str) -> Memory:
    svc, conn, _, provider = service
    memory = svc.create_explicit_memory(content, MemoryCategory.NOTE, (), _CID)
    await backfill_missing_embeddings(conn, provider, model_id=_MODEL, correlation_id=_CID)
    return memory


async def _remember_distractors(service, *, exclude_topic: str, count: int = 4) -> list[str]:
    """Inserts `count` memories about topics other than `exclude_topic`,
    each with its own real embedding, so a positive test case has actual
    differently-topiced competitors in the corpus. This is what makes the
    case's `results[0]` assertion meaningful: it proves the target won on
    topic relevance against real alternatives, not merely that it was the
    only memory that existed at all."""
    topics = [t for t in TopicEmbeddingProvider._TOPICS if t != exclude_topic][:count]
    contents = [_TOPIC_CONTENT[t] for t in topics]
    for content in contents:
        await _remember(service, content)
    return contents


async def test_case_1_pet_cat(service):
    await _remember(service, "I have a pet cat.")
    distractors = await _remember_distractors(service, exclude_topic="cat")
    svc, _, _, _ = service

    results = await svc.query_memories("What animal do I own?", 5, _CID)

    assert results and "cat" in results[0].content.lower()
    assert not any(r.content in distractors for r in results)


async def test_case_2_works_late_at_night(service):
    await _remember(service, "I prefer working late at night.")
    distractors = await _remember_distractors(service, exclude_topic="night")
    svc, _, _, _ = service

    results = await svc.query_memories(
        "Do I prefer working during the day or late at night?", 5, _CID
    )

    assert results and "night" in results[0].content.lower()
    assert not any(r.content in distractors for r in results)


async def test_case_3_sdet_career_target(service):
    await _remember(service, "My main career target is SDET.")
    distractors = await _remember_distractors(service, exclude_topic="sdet")
    svc, _, _, _ = service

    results = await svc.query_memories("What kind of testing job am I targeting?", 5, _CID)

    assert results and "sdet" in results[0].content.lower()
    assert not any(r.content in distractors for r in results)


async def test_case_4_iphone_daily_driver(service):
    await _remember(service, "I use an iPhone 12 as my main phone.")
    distractors = await _remember_distractors(service, exclude_topic="iphone")
    svc, _, _, _ = service

    results = await svc.query_memories("Which handset is my daily driver?", 5, _CID)

    assert results and "iphone" in results[0].content.lower()
    assert not any(r.content in distractors for r in results)


async def test_case_5_maltrace_project(service):
    await _remember(service, "I built MalTrace to analyze malware behavior.")
    distractors = await _remember_distractors(service, exclude_topic="maltrace")
    svc, _, _, _ = service

    results = await svc.query_memories("Which project did I make for malware analysis?", 5, _CID)

    assert results and "maltrace" in results[0].content.lower()
    assert not any(r.content in distractors for r in results)


async def test_negative_case_no_confident_match(service):
    distractors = await _remember_distractors(service, exclude_topic="recipe", count=5)
    svc, _, _, _ = service

    results = await svc.query_memories("best recipe for banana bread", 5, _CID)

    assert not any(r.content in distractors for r in results)
