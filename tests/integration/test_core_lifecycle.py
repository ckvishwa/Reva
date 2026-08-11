import pytest

from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.contracts.health import CoreStatus
from reva_core.shared.errors import StorageError


def _lifecycle(tmp_path) -> CoreLifecycle:
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    return CoreLifecycle(settings)


def test_health_before_startup_is_stopped(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    health = lifecycle.health()
    assert health.status == CoreStatus.STOPPED
    assert health.db_schema_version == 0


def test_startup_reports_healthy_with_schema_version(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    health = lifecycle.startup()
    try:
        assert health.status == CoreStatus.HEALTHY
        assert health.db_schema_version == 2
        assert health.started_at is not None
    finally:
        lifecycle.shutdown()


def test_shutdown_closes_connection_and_reports_stopped(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    lifecycle.startup()
    lifecycle.shutdown()

    assert lifecycle.health().status == CoreStatus.STOPPED
    with pytest.raises(StorageError):
        _ = lifecycle.connection


def test_startup_creates_database_file_on_disk(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    lifecycle.startup()
    try:
        assert (tmp_path / "reva.db").exists()
    finally:
        lifecycle.shutdown()


def test_local_token_raises_before_startup(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    with pytest.raises(StorageError):
        _ = lifecycle.local_token


def test_primary_device_id_raises_before_startup(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    with pytest.raises(StorageError):
        _ = lifecycle.primary_device_id


def test_local_token_and_primary_device_id_available_after_startup(tmp_path):
    lifecycle = _lifecycle(tmp_path)
    lifecycle.startup()
    try:
        assert len(lifecycle.local_token) >= 32
        assert lifecycle.primary_device_id
    finally:
        lifecycle.shutdown()


def test_primary_device_id_stable_across_restart(tmp_path):
    first = _lifecycle(tmp_path)
    first.startup()
    device_id = first.primary_device_id
    first.shutdown()

    second = _lifecycle(tmp_path)
    second.startup()
    try:
        assert second.primary_device_id == device_id
    finally:
        second.shutdown()


def test_startup_builds_embedding_provider(tmp_path):
    from reva_core.models.embedding_providers import OllamaEmbeddingProvider

    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings)

    lifecycle.startup()

    assert isinstance(lifecycle.embedding_provider, OllamaEmbeddingProvider)
    assert lifecycle.embedding_model_id == settings.embedding_model
    lifecycle.shutdown()


def test_startup_succeeds_even_when_embedding_backend_is_unreachable(tmp_path, monkeypatch):
    """Ollama is never running in CI. Startup with a non-empty memories
    table and an unreachable embedding backend must still reach HEALTHY —
    this is the core CI-safety guarantee for this slice."""
    from reva_core.shared.contracts.health import CoreStatus
    from reva_core.shared.contracts.memory import (
        Memory,
        MemoryCategory,
        MemorySourceReference,
        RetentionState,
    )
    from reva_core.shared.ids import new_id
    from reva_core.shared.time import utc_now
    from reva_core.storage.bootstrap import initialize_database
    from reva_core.storage.repositories.device_repository import DeviceRepository
    from reva_core.storage.repositories.memory_repository import MemoryRepository

    data_dir = tmp_path / "data"
    conn, _ = initialize_database(data_dir / "reva.db")
    # memories.origin_device_id is a NOT NULL FK to devices(id), so a real
    # device row must exist first (matches DeviceRepository usage elsewhere,
    # e.g. tests/integration/test_embedding_backfill.py's _insert_memory).
    device_id = DeviceRepository(conn).get_or_create_primary_device()
    now = utc_now()
    MemoryRepository(conn).insert(
        Memory(
            id=new_id(),
            category=MemoryCategory.NOTE,
            content="pre-existing memory",
            source=MemorySourceReference(origin_device_id=device_id, note="test"),
            tags=(),
            retention_state=RetentionState.ACTIVE,
            sync_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    conn.close()

    settings = load_settings(
        _env_file=None, data_dir=data_dir, embedding_model_api_base="http://127.0.0.1:1"
    )
    lifecycle = CoreLifecycle(settings)

    health = lifecycle.startup()

    assert health.status == CoreStatus.HEALTHY
    lifecycle.shutdown()


def test_startup_with_empty_memories_table_does_not_require_embedding_backend(tmp_path):
    from reva_core.shared.contracts.health import CoreStatus

    settings = load_settings(
        _env_file=None, data_dir=tmp_path / "data", embedding_model_api_base="http://127.0.0.1:1"
    )
    lifecycle = CoreLifecycle(settings)

    health = lifecycle.startup()

    assert health.status == CoreStatus.HEALTHY
    lifecycle.shutdown()
