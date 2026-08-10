def test_missing_auth_header_returns_401(client):
    response = client.post("/v1/memories", json={"content": "no header"})
    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"


def test_malformed_auth_header_returns_401(client):
    response = client.post(
        "/v1/memories",
        json={"content": "malformed header"},
        headers={"Authorization": "not-a-bearer-token"},
    )
    assert response.status_code == 401


def test_invalid_token_returns_401(client):
    response = client.post(
        "/v1/memories",
        json={"content": "wrong token"},
        headers={"Authorization": "Bearer wrong-token-value"},
    )
    assert response.status_code == 401


def test_valid_token_is_accepted(client, auth_headers):
    response = client.post(
        "/v1/memories", json={"content": "valid token test"}, headers=auth_headers
    )
    assert response.status_code == 201


def test_authentication_failed_audit_event_recorded(client, core, auth_headers):
    client.post(
        "/v1/memories",
        json={"content": "trigger failure"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    response = client.get("/v1/audit-events", headers=auth_headers)
    actions = [event["action"] for event in response.json()["events"]]
    assert "authentication_failed" in actions


def test_auth_still_denies_when_failure_audit_write_itself_fails(client, monkeypatch):
    """Auth enforcement must never depend on audit persistence succeeding."""
    from reva_core.shared.errors import StorageError
    from reva_core.storage.repositories.audit_repository import AuditRepository

    def broken_insert(self, event):
        raise StorageError("audit write failed")

    monkeypatch.setattr(AuditRepository, "insert", broken_insert)

    response = client.post(
        "/v1/memories",
        json={"content": "x"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
