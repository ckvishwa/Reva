def test_cloud_reasoning_settings_default_off_and_persist(client, core, auth_headers):
    initial = client.get("/v1/settings/reasoning", headers=auth_headers)
    assert initial.status_code == 200
    assert initial.json()["cloud_reasoning"] is False
    assert initial.json()["leaves_device"]["audio"] == "Never"
    enabled = client.patch(
        "/v1/settings/reasoning", json={"cloud_reasoning": True}, headers=auth_headers
    )
    assert enabled.status_code == 200
    assert core.cloud_reasoning.enabled is True


def test_cloud_reasoning_setting_requires_auth(client):
    assert client.patch("/v1/settings/reasoning", json={"cloud_reasoning": True}).status_code == 401


def test_anthropic_key_write_returns_no_secret(client, auth_headers, monkeypatch):
    stored = []
    monkeypatch.setattr("reva_core.planner.credentials.write_anthropic_key", stored.append)
    response = client.post(
        "/v1/settings/reasoning/key",
        json={"api_key": "test-secret-never-echo"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert stored == ["test-secret-never-echo"]
    assert "test-secret-never-echo" not in response.text
