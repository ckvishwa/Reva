"""Shared fixtures for API-level tests (integration/security/e2e)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle


@pytest.fixture
def core(tmp_path):
    """A started CoreLifecycle against a fresh tmp_path database.
    Caller is responsible for nothing — shutdown happens automatically.
    """
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    yield lifecycle
    lifecycle.shutdown()


@pytest.fixture
def client(core):
    """A TestClient wired to a started Core, plus the valid bearer token."""
    app = create_app(core)
    return TestClient(app)


@pytest.fixture
def auth_headers(core):
    return {"Authorization": f"Bearer {core.local_token}"}


def iter_effective_routes(app):
    """Flatten `app.routes` into (method, path) pairs.

    FastAPI's `include_router` wraps included routes in an internal
    `_IncludedRouter` object (not itself a `Route`/`APIRoute`) rather
    than flattening them into `app.routes` directly. Its real routes
    live on `.original_router.routes`. This helper hides that detail
    so route-enumeration security tests don't hardcode a private
    FastAPI implementation attribute in more than one place.
    """
    for route in app.routes:
        if hasattr(route, "original_router"):
            yield from iter_effective_routes_of(route.original_router)
        else:
            yield route


def iter_effective_routes_of(router):
    for route in router.routes:
        if hasattr(route, "original_router"):
            yield from iter_effective_routes_of(route.original_router)
        else:
            yield route
