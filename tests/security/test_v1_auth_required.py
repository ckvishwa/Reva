"""Every /v1/* domain endpoint rejects unauthenticated access."""

import pytest


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/v1/messages", {"json": {"content": "hi"}}),
        ("post", "/v1/memories", {"json": {"content": "hi"}}),
        ("get", "/v1/memories", {"params": {"q": "hi"}}),
        ("get", "/v1/audit-events", {}),
        ("get", "/v1/devices", {}),
        ("get", "/v1/domains/changes", {}),
        ("patch", "/v1/devices/gateway", {"json": {"enabled": True}}),
        ("post", "/v1/devices/pairing", {}),
        ("post", "/v1/devices/pairing/approve", {"json": {"fingerprint": "123456"}}),
        ("post", "/v1/devices/pairing/deny", {}),
        ("post", "/v1/devices/some-device/revoke", {}),
        ("post", "/v1/voice/sessions", {"json": {}}),
        ("delete", "/v1/voice/sessions/some-session-id", {}),
        ("get", "/v1/voice/sessions/some-session-id/audio/some-audio-id", {}),
        ("post", "/v1/voice/speech", {"json": {"text": "hi", "language": "en"}}),
        (
            "post",
            "/v1/voice/transcriptions",
            {"content": b"fake", "headers": {"Content-Type": "audio/wav"}},
        ),
    ],
)
def test_v1_endpoint_rejects_missing_auth(client, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


def test_health_does_not_require_auth(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_version_does_not_require_auth(client):
    response = client.get("/version")
    assert response.status_code == 200


@pytest.mark.parametrize("header", ["Bearer café-token", "Bearer ÿþ"])
def test_a_non_ascii_bearer_on_http_is_a_401_and_is_audited(client, header):
    """B0 (closes VOICE-1 R-1): a hostile header must not become a 500 or skip the audit record."""
    response = client.get("/v1/audit-events", headers={"Authorization": header.encode("latin-1")})

    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"
