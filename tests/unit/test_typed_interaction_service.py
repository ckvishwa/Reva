"""Explicit-memory service semantics, query normalization/ordering, and
bounded query limit — categorized as unit tests per the Phase 1A spec
even though they exercise a real (tmp_path) SQLite database, since each
test asserts one isolated service behavior."""

import pytest

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.shared.errors import ValidationError
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository

_EMBED_MODEL = "test-model"


class FailingEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        raise RuntimeError("embedding backend unreachable")


class SucceedingEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(vector=(0.1, 0.2), correlation_id=request.correlation_id)


@pytest.fixture
def service(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(conn, device_id)
    yield svc
    conn.close()


def _cid() -> str:
    import uuid

    return str(uuid.uuid4())


async def test_handle_typed_message_falls_back_when_provider_unavailable(tmp_path):
    from tests.fixtures.fake_providers import FailingLLMProvider

    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(conn, device_id, llm_provider=FailingLLMProvider())

    result = await svc.handle_typed_message("hello while provider is down", _cid())

    assert "unavailable" in result.reply.lower()
    assert "your request was received" in result.reply.lower()
    conn.close()


async def test_handle_typed_message_remember_still_saves_when_provider_unavailable(tmp_path):
    from tests.fixtures.fake_providers import FailingLLMProvider

    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(conn, device_id, llm_provider=FailingLLMProvider())

    result = await svc.handle_typed_message(
        "remember: memory still saves even if reasoning is down", _cid()
    )

    assert result.memory_id is not None
    assert "unavailable" in result.reply.lower()
    conn.close()


async def test_handle_typed_message_without_remember_creates_no_memory(service):
    result = await service.handle_typed_message("just chatting", _cid())
    assert result.memory_id is None
    assert "Received: just chatting" in result.reply


async def test_handle_typed_message_with_remember_creates_memory(service):
    result = await service.handle_typed_message("remember: REVA V1 uses push-to-talk", _cid())
    assert result.memory_id is not None
    assert "Saved as a memory" in result.reply


async def test_handle_typed_message_remember_is_case_insensitive(service):
    result = await service.handle_typed_message("REMEMBER: uppercase command works too", _cid())
    assert result.memory_id is not None


async def test_handle_typed_message_rejects_empty_content(service):
    with pytest.raises(ValidationError):
        await service.handle_typed_message("   ", _cid())


async def test_handle_typed_message_remember_with_no_content_raises(service):
    with pytest.raises(ValidationError):
        await service.handle_typed_message("remember:   ", _cid())


async def test_create_explicit_memory_rejects_empty_content(service):
    with pytest.raises(ValidationError):
        await service.create_explicit_memory("   ", MemoryCategory.NOTE, (), _cid())


async def test_create_explicit_memory_persists_and_returns_memory(service):
    memory = await service.create_explicit_memory(
        "REVA V1 uses push-to-talk, not always-on listening.",
        MemoryCategory.NOTE,
        ("voice", "v1"),
        _cid(),
    )
    assert memory.id
    assert memory.tags == ("voice", "v1")
    assert memory.source.note == "explicit_api_memory_creation"


async def test_query_memories_rejects_empty_query(service):
    with pytest.raises(ValidationError):
        await service.query_memories("   ", 20, _cid())


async def test_query_memories_returns_empty_list_when_no_match(service):
    await service.create_explicit_memory("unrelated content", MemoryCategory.NOTE, (), _cid())
    results = await service.query_memories("nonexistent-term-xyz", 20, _cid())
    assert results == []


async def test_query_memories_matches_case_insensitive_substring(service):
    await service.create_explicit_memory("REVA uses Push-To-Talk", MemoryCategory.NOTE, (), _cid())
    results = await service.query_memories("push-to-talk", 20, _cid())
    assert len(results) == 1


async def test_query_memories_orders_most_recently_updated_first(service):
    cid = _cid()
    first = await service.create_explicit_memory("alpha memory", MemoryCategory.NOTE, (), cid)
    second = await service.create_explicit_memory("alpha memory two", MemoryCategory.NOTE, (), cid)
    results = await service.query_memories("alpha", 20, cid)
    assert [m.id for m in results] == [second.id, first.id]


async def test_query_memories_respects_bounded_limit(service):
    cid = _cid()
    for i in range(5):
        await service.create_explicit_memory(f"bounded test {i}", MemoryCategory.NOTE, (), cid)
    results = await service.query_memories("bounded test", 2, cid)
    assert len(results) == 2


async def test_create_explicit_memory_embedding_failure_does_not_block_write(tmp_path):
    """Scenario B: the write survives an embed-on-write failure, no
    embedding row is created, the memory is still findable via the
    lexical fallback, and it remains eligible for the next backfill."""
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    svc = TypedInteractionService(
        conn,
        device_id,
        embedding_provider=FailingEmbeddingProvider(),
        embedding_model_id=_EMBED_MODEL,
    )
    cid = _cid()

    memory = await svc.create_explicit_memory(
        "no embedding available content", MemoryCategory.NOTE, (), cid
    )

    assert memory.content == "no embedding available content"
    assert MemoryEmbeddingRepository(conn).get(memory.id, _EMBED_MODEL) is None

    results = await svc.query_memories("no embedding available content", 5, cid)
    assert any(r.id == memory.id for r in results)

    backfill_result = await backfill_missing_embeddings(
        conn, SucceedingEmbeddingProvider(), model_id=_EMBED_MODEL, correlation_id=cid
    )

    assert backfill_result.embedded_count == 1
    assert MemoryEmbeddingRepository(conn).get(memory.id, _EMBED_MODEL) is not None

    conn.close()
