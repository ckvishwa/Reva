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
