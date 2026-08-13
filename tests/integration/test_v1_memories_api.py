from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.models.embedding import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from reva_core.orchestration.lifecycle import CoreLifecycle


class PhoneDinosaurEmbeddingProvider(EmbeddingProvider):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        text = request.text.lower()
        if "dinosaur" in text:
            vector = (0.0, 1.0, 0.0)
        elif "iphone" in text or "phone" in text:
            vector = (1.0, 0.0, 0.0)
        else:
            vector = (0.0, 0.0, 1.0)
        return EmbeddingResult(vector=vector, correlation_id=request.correlation_id)


def _use_phone_dinosaur_embeddings(core) -> None:
    core._embedding_provider = PhoneDinosaurEmbeddingProvider()  # noqa: SLF001


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


def test_query_memories_phone_positive_and_dinosaur_negative(client, core, auth_headers):
    _use_phone_dinosaur_embeddings(core)
    for content in [
        "I use an iPhone 12 as my main phone.",
        "What phone do I use?",
    ]:
        response = client.post("/v1/memories", json={"content": content}, headers=auth_headers)
        assert response.status_code == 201

    positive = client.get(
        "/v1/memories", params={"q": "Do I have an iPhone 12?"}, headers=auth_headers
    )
    assert positive.status_code == 200
    positive_contents = [item["content"] for item in positive.json()["results"]]
    assert "I use an iPhone 12 as my main phone." in positive_contents

    negative = client.get(
        "/v1/memories", params={"q": "What is my favorite dinosaur?"}, headers=auth_headers
    )
    assert negative.status_code == 200
    assert negative.json()["results"] == []


def test_query_memories_isolated_data_dir_owner_boundary(tmp_path, client, core, auth_headers):
    _use_phone_dinosaur_embeddings(core)
    response = client.post(
        "/v1/memories",
        json={"content": "I use an iPhone 12 as my main phone."},
        headers=auth_headers,
    )
    assert response.status_code == 201

    other_settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "other-owner",
        assistant_orchestrator="deterministic",
        tts_enabled=False,
    )
    other_core = CoreLifecycle(other_settings)
    other_core.startup()
    try:
        _use_phone_dinosaur_embeddings(other_core)
        other_client = TestClient(create_app(other_core))
        other_headers = {"Authorization": f"Bearer {other_core.local_token}"}

        other_response = other_client.get(
            "/v1/memories",
            params={"q": "Do I have an iPhone 12?"},
            headers=other_headers,
        )

        assert other_response.status_code == 200
        assert other_response.json()["results"] == []
    finally:
        other_core.shutdown()


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
