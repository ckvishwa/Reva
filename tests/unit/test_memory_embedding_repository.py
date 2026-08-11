"""MemoryEmbeddingRepository: a derived, rebuildable index over `memories`
— see reva_core/shared/contracts/memory.py's module docstring for why
this is a separate table, never a column on `memories` itself."""

from __future__ import annotations

import struct

import pytest

from reva_core.shared.contracts.memory import Memory, MemoryCategory, MemorySourceReference, RetentionState
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.memory_embedding_repository import MemoryEmbeddingRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository


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


def test_upsert_and_get_roundtrip(store):
    memory_id = _insert_memory(store, "I have a pet cat.")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "test-model", (0.1, 0.2, 0.3))

    assert repo.get(memory_id, "test-model") == pytest.approx((0.1, 0.2, 0.3))


def test_get_returns_none_when_missing(store):
    memory_id = _insert_memory(store, "no embedding yet")
    repo = MemoryEmbeddingRepository(store)

    assert repo.get(memory_id, "test-model") is None


def test_upsert_is_idempotent_per_memory_and_model(store):
    memory_id = _insert_memory(store, "overwrite me")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "test-model", (1.0, 0.0))
    repo.upsert(memory_id, "test-model", (0.0, 1.0))

    assert repo.get(memory_id, "test-model") == pytest.approx((0.0, 1.0))
    assert len(repo.all_for_model("test-model")) == 1


def test_missing_for_model_returns_only_unembedded_active_memories(store):
    embedded_id = _insert_memory(store, "already embedded")
    unembedded_id = _insert_memory(store, "not embedded yet")
    repo = MemoryEmbeddingRepository(store)
    repo.upsert(embedded_id, "test-model", (0.1,))

    pending = repo.missing_for_model("test-model", batch_size=100)

    pending_ids = {memory_id for memory_id, _content in pending}
    assert pending_ids == {unembedded_id}


def test_missing_for_model_respects_batch_size(store):
    for i in range(5):
        _insert_memory(store, f"memory {i}")
    repo = MemoryEmbeddingRepository(store)

    pending = repo.missing_for_model("test-model", batch_size=2)

    assert len(pending) == 2


def test_all_for_model_skips_corrupt_rows_without_raising(store):
    memory_id = _insert_memory(store, "will be corrupted")
    repo = MemoryEmbeddingRepository(store)
    repo.upsert(memory_id, "test-model", (0.1, 0.2, 0.3))
    # Simulate corruption: overwrite the BLOB with a length that doesn't
    # divide evenly into float32 records.
    store.execute(
        "UPDATE memory_embeddings SET vector = ? WHERE memory_id = ? AND model_id = ?",
        (b"\x01\x02\x03", memory_id, "test-model"),
    )

    result = repo.all_for_model("test-model")

    assert result == []


def test_different_models_are_independent(store):
    memory_id = _insert_memory(store, "multi-model memory")
    repo = MemoryEmbeddingRepository(store)

    repo.upsert(memory_id, "model-a", (1.0, 0.0))
    repo.upsert(memory_id, "model-b", (0.0, 1.0))

    assert repo.get(memory_id, "model-a") == pytest.approx((1.0, 0.0))
    assert repo.get(memory_id, "model-b") == pytest.approx((0.0, 1.0))
