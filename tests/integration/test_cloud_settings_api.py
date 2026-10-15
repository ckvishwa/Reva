"""B1.7: /v1/settings/cloud: opt-in, per-domain consent, write-only key."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.security.credential_store import InMemorySecretStore

KEY = "sk-ant-api03-test-key-do-not-use-0123456789"


@pytest.fixture
def rig(tmp_path):
    secrets = InMemorySecretStore()
    core = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path), anthropic_secret_store=secrets
    )
    core.startup()
    client = TestClient(create_app(core))
    yield client, {"Authorization": f"Bearer {core.local_token}"}, secrets, core
    core.shutdown()


def test_the_defaults_are_everything_off_with_a_disclosure(rig) -> None:
    client, headers, _, _ = rig

    body = client.get("/v1/settings/cloud", headers=headers).json()

    assert body["enabled"] is False and body["key_configured"] is False
    assert set(body["domains"]) == {
        "memory", "finance", "health", "coach", "career", "learn", "cyber", "personal",
    }  # fmt: skip
    assert not any(body["domains"].values())
    assert "Your voice or any audio" in body["disclosure"]["never_sent"]
    assert body["disclosure"]["provider"].startswith("Anthropic")


def test_every_route_needs_the_bearer_token(rig) -> None:
    client, _, _, _ = rig

    assert client.get("/v1/settings/cloud").status_code == 401
    assert client.put("/v1/settings/cloud", json={"enabled": False}).status_code == 401
    assert client.put("/v1/settings/cloud/key", json={"api_key": KEY}).status_code == 401
    assert client.delete("/v1/settings/cloud/key").status_code == 401


def test_cloud_cannot_be_switched_on_without_a_key(rig) -> None:
    client, headers, _, _ = rig

    response = client.put("/v1/settings/cloud", headers=headers, json={"enabled": True})

    assert response.status_code == 409 and response.json()["error"] == "key_required"
    assert client.get("/v1/settings/cloud", headers=headers).json()["enabled"] is False


def test_storing_a_key_never_echoes_it_and_lets_cloud_be_switched_on(rig) -> None:
    client, headers, secrets, _ = rig

    stored = client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": KEY})
    switched = client.put("/v1/settings/cloud", headers=headers, json={"enabled": True})
    read_back = client.get("/v1/settings/cloud", headers=headers)

    assert stored.status_code == 200 and stored.json()["key_configured"] is True
    assert switched.json()["enabled"] is True
    for response in (stored, switched, read_back):
        assert KEY not in response.text and "sk-ant" not in response.text
    assert secrets.read() == KEY


@pytest.mark.parametrize(
    "bad",
    ["short", "x" * 600, "sk-ant-has space inside-0123456789", "not-an-anthropic-key-0123456789"],
)
def test_malformed_keys_are_refused_and_not_stored(rig, bad: str) -> None:
    client, headers, secrets, _ = rig

    response = client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": bad})

    assert response.status_code == 422
    assert bad not in response.text
    assert secrets.read() is None


def test_unknown_domains_and_extra_fields_are_refused(rig) -> None:
    client, headers, _, _ = rig

    unknown = client.put("/v1/settings/cloud", headers=headers, json={"domains": {"bank": True}})
    extra = client.put("/v1/settings/cloud", headers=headers, json={"enabled": False, "x": 1})

    assert unknown.status_code == 422 and unknown.json()["error"] == "unknown_domain"
    assert extra.status_code == 422


def test_domain_consent_is_saved_per_domain_and_survives_a_restart(rig, tmp_path) -> None:
    client, headers, secrets, core = rig
    client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": KEY})
    client.put(
        "/v1/settings/cloud", headers=headers, json={"enabled": True, "domains": {"coach": True}}
    )

    body = client.get("/v1/settings/cloud", headers=headers).json()
    assert body["domains"]["coach"] is True
    assert body["domains"]["finance"] is False and body["domains"]["memory"] is False
    saved = json.loads((core.settings.data_dir / "cloud_settings.json").read_text(encoding="utf-8"))
    assert saved["domains"]["coach"] is True
    assert KEY not in json.dumps(saved)


def test_removing_the_key_switches_cloud_off(rig) -> None:
    client, headers, secrets, _ = rig
    client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": KEY})
    client.put("/v1/settings/cloud", headers=headers, json={"enabled": True})

    response = client.delete("/v1/settings/cloud/key", headers=headers)

    assert response.json()["enabled"] is False and response.json()["key_configured"] is False
    assert secrets.read() is None


def test_changes_are_audited_without_the_key(rig) -> None:
    client, headers, _, core = rig
    client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": KEY})
    client.put(
        "/v1/settings/cloud", headers=headers, json={"enabled": True, "domains": {"coach": True}}
    )

    events = client.get("/v1/audit-events", headers=headers).json()["events"]
    actions = [e["action"] for e in events]

    assert "cloud_key_stored" in actions and "cloud_settings_changed" in actions
    assert KEY not in json.dumps(events)


def test_under_pytest_the_default_store_refuses_so_real_keys_are_untouched(tmp_path) -> None:
    core = CoreLifecycle(load_settings(_env_file=None, data_dir=tmp_path))
    core.startup()
    try:
        client = TestClient(create_app(core))
        headers = {"Authorization": f"Bearer {core.local_token}"}

        response = client.put("/v1/settings/cloud/key", headers=headers, json={"api_key": KEY})

        assert response.status_code == 503
        assert client.get("/v1/settings/cloud", headers=headers).json()["key_configured"] is False
    finally:
        core.shutdown()


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": 12345},
        {"key": KEY},  # wrong field name must not echo the key either
        {"api_key": KEY, "extra": 1},
        ["not", "an", "object"],
    ],
)
def test_a_wrongly_shaped_key_request_never_echoes_what_was_sent(rig, body) -> None:
    client, headers, secrets, _ = rig

    response = client.put("/v1/settings/cloud/key", headers=headers, json=body)

    assert response.status_code == 422
    assert KEY not in response.text and "sk-ant" not in response.text
    assert secrets.read() is None


def test_a_key_request_that_is_not_json_is_refused(rig) -> None:
    client, headers, secrets, _ = rig

    response = client.put(
        "/v1/settings/cloud/key",
        headers={**headers, "Content-Type": "application/json"},
        content=b"{" + KEY.encode(),
    )

    assert response.status_code == 422 and KEY not in response.text
    assert secrets.read() is None
