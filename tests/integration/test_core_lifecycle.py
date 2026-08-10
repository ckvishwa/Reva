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
        assert health.db_schema_version == 1
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
