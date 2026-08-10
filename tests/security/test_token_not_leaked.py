"""Invalid token must not leak token material in logs or responses;
Authorization header must be redacted from structured logs; a valid
token must only unlock the Phase 1A endpoints, nothing else."""

import io
import json

from reva_core.shared.logging import configure_logging, get_logger


def test_401_response_never_contains_the_real_token(client, core):
    response = client.post(
        "/v1/memories",
        json={"content": "x"},
        headers={"Authorization": "Bearer wrong-value"},
    )
    assert core.local_token not in response.text


def test_valid_request_response_never_contains_the_token(client, core, auth_headers):
    response = client.post(
        "/v1/memories", json={"content": "token leak check"}, headers=auth_headers
    )
    assert core.local_token not in response.text


def test_authorization_header_redacted_in_structured_logs():
    stream = io.StringIO()
    configure_logging(level="info", stream=stream)
    logger = get_logger("test")
    logger.info("request received", extra={"authorization": "Bearer super-secret-token-value"})
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    serialized = json.dumps(payload)
    assert "super-secret-token-value" not in serialized
    assert payload["metadata"]["authorization"] == "***REDACTED***"


def test_valid_token_does_not_unlock_nonexistent_tool_endpoint(client, auth_headers):
    response = client.post("/v1/tools/execute", json={}, headers=auth_headers)
    assert response.status_code == 404


def test_authentication_failed_audit_metadata_has_no_token_material(client, core, auth_headers):
    client.post(
        "/v1/memories",
        json={"content": "x"},
        headers={"Authorization": "Bearer wrong-value-should-not-be-logged"},
    )
    response = client.get("/v1/audit-events", headers=auth_headers)
    failures = [e for e in response.json()["events"] if e["action"] == "authentication_failed"]
    assert failures
    for event in failures:
        serialized = json.dumps(event)
        assert "wrong-value-should-not-be-logged" not in serialized
        assert core.local_token not in serialized
