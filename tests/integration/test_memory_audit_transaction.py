"""Memory creation and its audit event must succeed or fail together."""

import uuid

import pytest

from reva_core.orchestration.typed_interaction import TypedInteractionService
from reva_core.shared.contracts.memory import MemoryCategory
from reva_core.shared.errors import StorageError
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.audit_repository import AuditRepository
from reva_core.storage.repositories.device_repository import DeviceRepository


async def test_memory_creation_rolls_back_if_second_audit_event_fails(tmp_path, monkeypatch):
    conn, _ = initialize_database(tmp_path / "reva.db")
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    service = TypedInteractionService(conn, device_id)

    call_count = {"n": 0}
    original_insert = AuditRepository.insert

    def failing_insert(self, event):
        call_count["n"] += 1
        if call_count["n"] == 2:  # the "memory_created" event, after the memory row was inserted
            raise StorageError("simulated audit failure")
        return original_insert(self, event)

    monkeypatch.setattr(AuditRepository, "insert", failing_insert)

    with pytest.raises(StorageError):
        await service.create_explicit_memory(
            "should not survive", MemoryCategory.NOTE, (), str(uuid.uuid4())
        )

    monkeypatch.setattr(AuditRepository, "insert", original_insert)

    memory_rows = conn.execute("SELECT * FROM memories").fetchall()
    audit_rows = conn.execute("SELECT * FROM audit_events").fetchall()
    assert memory_rows == []
    assert audit_rows == []

    conn.close()
