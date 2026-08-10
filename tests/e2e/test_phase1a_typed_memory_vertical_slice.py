"""The one Phase 1A end-to-end test (real SQLite, real FastAPI, real
auth; the LLM call goes through the deterministic fake provider, no
network, no cloud credential):

bootstrap clean local database
-> authenticated Core test client
-> submit explicit-memory request
-> verify memory_created audit event
-> reinitialize Core against same database (simulated restart)
-> authenticate again
-> query saved memory
-> verify correct content and source reference
"""

from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle

_MEMORY_CONTENT = "REVA V1 uses push-to-talk, not always-on listening."


def test_typed_memory_vertical_slice_survives_restart(tmp_path):
    # --- bootstrap clean local database, start authenticated Core client ---
    settings = load_settings(_env_file=None, data_dir=tmp_path)
    first_lifecycle = CoreLifecycle(settings)
    first_lifecycle.startup()
    first_client = TestClient(create_app(first_lifecycle))
    first_token = first_lifecycle.local_token
    first_headers = {"Authorization": f"Bearer {first_token}"}

    # --- submit explicit-memory request ---
    create_response = first_client.post(
        "/v1/memories", json={"content": _MEMORY_CONTENT}, headers=first_headers
    )
    assert create_response.status_code == 201
    memory_id = create_response.json()["id"]

    # --- verify memory_created audit event ---
    audit_response = first_client.get("/v1/audit-events", headers=first_headers)
    actions = [e["action"] for e in audit_response.json()["events"]]
    assert "memory_create_requested" in actions
    assert "memory_created" in actions

    first_lifecycle.shutdown()

    # --- reinitialize Core against same database (simulated restart) ---
    second_lifecycle = CoreLifecycle(settings)
    second_lifecycle.startup()
    second_client = TestClient(create_app(second_lifecycle))

    # A fresh restart must not rotate the token — it's read from the
    # same on-disk file, so "authenticate again" uses the same value.
    assert second_lifecycle.local_token == first_token
    second_headers = {"Authorization": f"Bearer {second_lifecycle.local_token}"}

    # --- query saved memory ---
    query_response = second_client.get(
        "/v1/memories", params={"q": "push-to-talk"}, headers=second_headers
    )
    assert query_response.status_code == 200
    results = query_response.json()["results"]

    # --- verify correct content and source reference ---
    assert len(results) == 1
    assert results[0]["id"] == memory_id
    assert results[0]["content"] == _MEMORY_CONTENT
    assert results[0]["source"]["origin_device_id"] == second_lifecycle.primary_device_id
    assert results[0]["source"]["note"] == "explicit_api_memory_creation"

    second_lifecycle.shutdown()
