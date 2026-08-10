def test_create_memory_persists_to_sqlite(client, core, auth_headers):
    response = client.post(
        "/v1/memories",
        json={"content": "REVA V1 uses push-to-talk, not always-on listening."},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "note"

    row = core.connection.execute(
        "SELECT content FROM memories WHERE id = ?", (body["id"],)
    ).fetchone()
    assert row["content"] == "REVA V1 uses push-to-talk, not always-on listening."


def test_create_memory_with_tags_and_category(client, auth_headers):
    response = client.post(
        "/v1/memories",
        json={"content": "tagged memory", "category": "decision", "tags": ["voice", "v1"]},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["category"] == "decision"


def test_create_memory_source_reference_persisted(client, core, auth_headers):
    response = client.post(
        "/v1/memories", json={"content": "source ref test"}, headers=auth_headers
    )
    memory_id = response.json()["id"]

    row = core.connection.execute(
        "SELECT origin_device_id, source_note FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    assert row["origin_device_id"] == core.primary_device_id
    assert row["source_note"] == "explicit_api_memory_creation"


def test_query_memories_returns_source_metadata(client, auth_headers):
    client.post("/v1/memories", json={"content": "queryable memory content"}, headers=auth_headers)
    response = client.get("/v1/memories", params={"q": "queryable"}, headers=auth_headers)
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["source"]["origin_device_id"]
    assert results[0]["source"]["note"] == "explicit_api_memory_creation"


def test_query_memories_empty_result_is_safe(client, auth_headers):
    response = client.get(
        "/v1/memories", params={"q": "nothing-matches-this-xyz"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_query_memories_rejects_missing_query_param(client, auth_headers):
    response = client.get("/v1/memories", headers=auth_headers)
    assert response.status_code == 422


def test_query_memories_rejects_oversized_limit(client, auth_headers):
    response = client.get("/v1/memories", params={"q": "x", "limit": 1000}, headers=auth_headers)
    assert response.status_code == 422


def test_create_memory_rejects_empty_content(client, auth_headers):
    response = client.post("/v1/memories", json={"content": "  "}, headers=auth_headers)
    assert response.status_code == 422


def test_create_memory_rejects_oversized_content(client, auth_headers):
    response = client.post("/v1/memories", json={"content": "x" * 8001}, headers=auth_headers)
    assert response.status_code == 422
