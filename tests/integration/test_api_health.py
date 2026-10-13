from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle


def _client(tmp_path) -> tuple[TestClient, CoreLifecycle]:
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    app = create_app(lifecycle)
    return TestClient(app), lifecycle


def test_health_endpoint_reports_healthy(tmp_path):
    client, lifecycle = _client(tmp_path)
    try:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["db_schema_version"] == 3
    finally:
        lifecycle.shutdown()


def test_version_endpoint_reports_package_version(tmp_path):
    client, lifecycle = _client(tmp_path)
    try:
        response = client.get("/version")
        assert response.status_code == 200
        assert response.json() == {"version": "0.1.0"}
    finally:
        lifecycle.shutdown()
