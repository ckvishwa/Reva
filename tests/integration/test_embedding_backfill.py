"""Restart-safe embedding backfill: existing memories without embeddings
stay readable/searchable; backfill converges to zero pending on rerun;
one failing record never corrupts the rest."""

from __future__ import annotations

import pytest

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_CID = "55555555-5555-5555-5555-555555555555"
_MODEL = "test-model"


class SucceedingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        return EmbeddingResult(vector=(0.1, 0.2), correlation_id=request.correlation_id)


class FailOnKeywordProvider(EmbeddingProvider):
    def __init__(self, failing_keyword: str) -> None:
        self._failing_keyword = failing_keyword

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if self._failing_keyword in request.text:
            raise RuntimeError("simulated embedding failure")
        return EmbeddingResult(vector=(0.1, 0.2), correlation_id=request.correlation_id)


@pytest.fixture
def store(tmp_path):
    conn, _ = initialize_database(tmp_path / "reva.db")
    yield conn
    conn.close()


def _insert_memory(conn, content: str) -> str:
    now = utc_now()
    memory_id = new_id()
    device_id = new_id()
    # Create the device that will be referenced by the memory's origin_device_id
    conn.execute(
        "INSERT INTO devices (id, display_name, platform, paired_at) VALUES (?, ?, ?, ?)",
        (device_id, "Test Device", "test", now.isoformat()),
    )
    MemoryRepository(conn).insert(
        Memory(
            id=memory_id,
            category=MemoryCategory.NOTE,
            content=content,
            source=MemorySourceReference(origin_device_id=device_id, note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    return memory_id


async def test_backfill_embeds_all_missing_memories(store):
    ids = [_insert_memory(store, f"memory {i}") for i in range(3)]

    result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 3
    assert result.failed_count == 0
    embeddings = MemoryEmbeddingRepository(store)
    for memory_id in ids:
        assert embeddings.get(memory_id, _MODEL) is not None


async def test_backfill_is_idempotent_on_rerun(store):
    _insert_memory(store, "already backfilled")
    await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    second_result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert second_result.embedded_count == 0


async def test_backfill_skips_failing_record_without_stopping_the_rest(store):
    good_id = _insert_memory(store, "good memory")
    bad_id = _insert_memory(store, "BOOM memory")
    other_good_id = _insert_memory(store, "another good memory")
    provider = FailOnKeywordProvider(failing_keyword="BOOM")

    result = await backfill_missing_embeddings(
        store, provider, model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 2
    assert result.failed_count == 1
    assert result.failed_memory_ids == (bad_id,)
    embeddings = MemoryEmbeddingRepository(store)
    assert embeddings.get(good_id, _MODEL) is not None
    assert embeddings.get(other_good_id, _MODEL) is not None
    assert embeddings.get(bad_id, _MODEL) is None


async def test_backfill_does_not_delete_or_alter_source_memory_on_failure(store):
    bad_id = _insert_memory(store, "BOOM memory")
    provider = FailOnKeywordProvider(failing_keyword="BOOM")

    await backfill_missing_embeddings(store, provider, model_id=_MODEL, correlation_id=_CID)

    memory = MemoryRepository(store).query("BOOM", 10)
    assert len(memory) == 1
    assert memory[0].id == bad_id


async def test_backfill_with_zero_pending_memories_is_a_safe_noop(store):
    result = await backfill_missing_embeddings(
        store, SucceedingProvider(), model_id=_MODEL, correlation_id=_CID
    )

    assert result.embedded_count == 0
    assert result.failed_count == 0
