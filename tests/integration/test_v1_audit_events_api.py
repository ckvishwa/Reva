def test_audit_events_requires_auth(client):
    response = client.get("/v1/audit-events")
    assert response.status_code == 401


def test_audit_events_lists_recent_events(client, auth_headers):
    client.post("/v1/memories", json={"content": "audit trail test"}, headers=auth_headers)

    response = client.get("/v1/audit-events", headers=auth_headers)
    assert response.status_code == 200
    actions = [e["action"] for e in response.json()["events"]]
    assert "memory_create_requested" in actions
    assert "memory_created" in actions


def test_audit_events_respects_limit(client, auth_headers):
    for i in range(5):
        client.post("/v1/memories", json={"content": f"bulk memory {i}"}, headers=auth_headers)

    response = client.get("/v1/audit-events", params={"limit": 2}, headers=auth_headers)
    assert len(response.json()["events"]) == 2


def test_audit_events_rejects_oversized_limit(client, auth_headers):
    response = client.get("/v1/audit-events", params={"limit": 1000}, headers=auth_headers)
    assert response.status_code == 422
