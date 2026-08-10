"""Memory content is always parameterized SQL — user text cannot alter
query structure, cause errors, or otherwise misbehave."""

_INJECTION_PAYLOADS = [
    "'; DROP TABLE memories; --",
    "' OR '1'='1",
    "Robert'); DROP TABLE memories;--",
    "%' OR '%'='",
    "memory with %wildcards% and _underscores_",
]


def test_sql_injection_payloads_are_stored_as_literal_text(client, core, auth_headers):
    for payload in _INJECTION_PAYLOADS:
        response = client.post("/v1/memories", json={"content": payload}, headers=auth_headers)
        assert response.status_code == 201, payload
        assert response.json()["id"]

    tables = {
        row["name"]
        for row in core.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "memories" in tables
    count = core.connection.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
    assert count == len(_INJECTION_PAYLOADS)


def test_query_with_wildcard_characters_does_not_error(client, auth_headers):
    client.post(
        "/v1/memories", json={"content": "contains 100% of the _budget_"}, headers=auth_headers
    )
    response = client.get("/v1/memories", params={"q": "100%"}, headers=auth_headers)
    assert response.status_code == 200


def test_service_still_functions_after_injection_attempts(client, auth_headers):
    client.post(
        "/v1/memories", json={"content": "'; DROP TABLE memories; --"}, headers=auth_headers
    )
    response = client.post(
        "/v1/memories",
        json={"content": "normal memory after injection attempt"},
        headers=auth_headers,
    )
    assert response.status_code == 201
