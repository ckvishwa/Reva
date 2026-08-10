"""Every /v1/* domain endpoint rejects unauthenticated access."""

import pytest


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/v1/messages", {"json": {"content": "hi"}}),
        ("post", "/v1/memories", {"json": {"content": "hi"}}),
        ("get", "/v1/memories", {"params": {"q": "hi"}}),
        ("get", "/v1/audit-events", {}),
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
