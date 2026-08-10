"""No response body ever contains a stack trace, database path, or
raw exception text — regardless of what fails server-side."""

from fastapi.testclient import TestClient

from reva_core.shared.errors import StorageError
from reva_core.storage.repositories.memory_repository import MemoryRepository


def test_storage_error_returns_safe_generic_body(core, auth_headers, monkeypatch):
    def broken_insert(self, memory):
        raise RuntimeError(f"disk write failed at {core.connection}")

    monkeypatch.setattr(MemoryRepository, "insert", broken_insert)

    # raise_server_exceptions=False: Starlette's TestClient re-raises
    # server-side exceptions by default (to surface app bugs during
    # normal testing) even when a registered handler already produced
    # a safe response — exactly the path this test needs to inspect.
    from reva_core.api.app import create_app

    unsafe_client = TestClient(create_app(core), raise_server_exceptions=False)
    response = unsafe_client.post(
        "/v1/memories", json={"content": "trigger internal error"}, headers=auth_headers
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal_error"
    text = response.text
    assert "Traceback" not in text
    assert ".db" not in text
    assert "RuntimeError" not in text


def test_storage_error_specifically_returns_safe_generic_body(core, auth_headers, monkeypatch):
    def broken_insert(self, memory):
        raise StorageError("disk write failed against C:\\Users\\test\\AppData\\reva.db")

    monkeypatch.setattr(MemoryRepository, "insert", broken_insert)

    from reva_core.api.app import create_app

    unsafe_client = TestClient(create_app(core), raise_server_exceptions=False)
    response = unsafe_client.post(
        "/v1/memories", json={"content": "trigger storage error"}, headers=auth_headers
    )

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert ".db" not in response.text


def test_404_response_is_safe(client, auth_headers):
    response = client.get("/v1/nonexistent-route", headers=auth_headers)
    assert response.status_code == 404
    assert "Traceback" not in response.text
