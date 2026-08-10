def test_typed_message_returns_deterministic_ack(client, auth_headers):
    response = client.post("/v1/messages", json={"content": "hello REVA"}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "hello REVA" in body["reply"]
    assert body["memory_created"] is None


def test_typed_message_persists_conversation_and_message(client, core, auth_headers):
    client.post("/v1/messages", json={"content": "persisted message"}, headers=auth_headers)

    row = core.connection.execute(
        "SELECT content FROM messages WHERE content = ?", ("persisted message",)
    ).fetchone()
    assert row is not None


def test_typed_message_remember_command_creates_memory(client, core, auth_headers):
    response = client.post(
        "/v1/messages",
        json={"content": "remember: V1 uses push-to-talk, not always-on listening."},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["memory_created"] is not None

    row = core.connection.execute(
        "SELECT content, source_message_id, source_conversation_id FROM memories WHERE id = ?",
        (body["memory_created"],),
    ).fetchone()
    assert row["content"] == "V1 uses push-to-talk, not always-on listening."
    assert row["source_message_id"] is not None
    assert row["source_conversation_id"] is not None


def test_typed_message_rejects_empty_content(client, auth_headers):
    response = client.post("/v1/messages", json={"content": "   "}, headers=auth_headers)
    assert response.status_code == 422


def test_typed_message_rejects_oversized_content(client, auth_headers):
    response = client.post("/v1/messages", json={"content": "x" * 4001}, headers=auth_headers)
    assert response.status_code == 422


def test_typed_message_remember_with_empty_body_returns_400(client, auth_headers):
    response = client.post("/v1/messages", json={"content": "remember:   "}, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]


def test_typed_message_correlation_id_propagates(client, auth_headers):
    import uuid

    cid = str(uuid.uuid4())
    response = client.post(
        "/v1/messages",
        json={"content": "hi", "correlation_id": cid},
        headers=auth_headers,
    )
    assert response.json()["correlation_id"] == cid
