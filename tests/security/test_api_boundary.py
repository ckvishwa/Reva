"""API boundary security tests: only known routes exist, no SQL/domain
logic reachable outside them. Updated for Phase 1A, which deliberately
adds the `/v1/*` domain routes on top of Phase 0's `/health`/`/version`.
"""

from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from tests.conftest import iter_effective_routes

_ALLOWED_PATHS = {
    "/health",
    "/version",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
    "/v1/messages",
    "/v1/memories",
    "/v1/audit-events",
}


def test_only_known_routes_exist(tmp_path):
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    try:
        app = create_app(lifecycle)
        paths = {route.path for route in iter_effective_routes(app)}
        unexpected = {p for p in paths if p not in _ALLOWED_PATHS}
        assert not unexpected, f"unexpected domain route(s) exposed: {unexpected}"
    finally:
        lifecycle.shutdown()


def test_unknown_route_returns_404_not_a_stack_trace(tmp_path):
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    try:
        app = create_app(lifecycle)
        client = TestClient(app)
        response = client.get("/memories")
        assert response.status_code == 404
    finally:
        lifecycle.shutdown()
