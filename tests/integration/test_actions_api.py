"""B3a: /v1/actions/* end to end through the HTTP API (AR-AGT-004/005/014, AR-WIN-008/009)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.orchestration.lifecycle import CoreLifecycle

OPEN = {"capability": "windows.app.open", "args": {"app_key": "notepad"}}
CLOSE = {"capability": "windows.app.close", "args": {"app_key": "notepad"}}
EVIDENCE = {"kind": "process_started", "ref": "pid:1 window:0x2"}


@pytest.fixture
def rig(tmp_path):
    core = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path, domain_keystore="memory"),
        grant_key_provider=InMemoryKeyProvider(),
        domain_key_provider=InMemoryKeyProvider(),
    )
    core.startup()
    client = TestClient(create_app(core))
    yield client, {"Authorization": f"Bearer {core.local_token}"}, core, tmp_path
    core.shutdown()


def test_an_open_is_granted_with_a_signed_order_and_no_success_claim(rig) -> None:
    client, headers, _, _ = rig

    response = client.post("/v1/actions/proposals", json=OPEN, headers=headers)

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "granted" and body["tier"] == "T1" and body["speak"] is None
    assert body["order"]["grant"]["capability"] == "windows.app.open"
    assert len(body["order"]["signature"]) >= 80
    assert body["order"]["args"] == {"app_key": "notepad"}


def test_the_executor_report_with_evidence_is_the_only_source_of_the_success_sentence(rig) -> None:
    client, headers, _, _ = rig
    order = client.post("/v1/actions/proposals", json=OPEN, headers=headers).json()
    action, grant = order["action_id"], order["order"]["grant"]["grant_id"]

    after = client.put(
        f"/v1/actions/{action}",
        json={"grant_id": grant, "status": "verified", "evidence": EVIDENCE},
        headers=headers,
    ).json()
    status = client.get(f"/v1/actions/{action}", headers=headers).json()

    assert after["status"] == "verified" and after["speak"] == "Opened Notepad."
    assert (
        status["status"] == "verified" and status["order"] is None
    )  # a GET never re-issues a grant


def test_verified_without_evidence_is_unknown_over_http_too(rig) -> None:
    client, headers, _, _ = rig
    order = client.post("/v1/actions/proposals", json=OPEN, headers=headers).json()

    after = client.put(
        f"/v1/actions/{order['action_id']}",
        json={"grant_id": order["order"]["grant"]["grant_id"], "status": "verified"},
        headers=headers,
    ).json()

    assert after["status"] == "unknown" and "opened" not in after["speak"].lower()


def test_a_wrong_grant_id_is_a_403_and_changes_nothing(rig) -> None:
    client, headers, _, _ = rig
    order = client.post("/v1/actions/proposals", json=OPEN, headers=headers).json()
    url = f"/v1/actions/{order['action_id']}"

    response = client.put(
        url,
        json={"grant_id": "made-up", "status": "verified", "evidence": EVIDENCE},
        headers=headers,
    )

    assert response.status_code == 403
    assert client.get(url, headers=headers).json()["status"] == "granted"


def test_a_close_waits_for_a_click_and_a_spoken_yes_is_not_one(rig) -> None:
    client, headers, _, _ = rig
    asked = client.post("/v1/actions/proposals", json=CLOSE, headers=headers).json()
    url = f"/v1/actions/{asked['action_id']}/approval"

    assert asked["status"] == "awaiting_approval" and asked["order"] is None
    spoken = client.post(url, json={"decision": "approve", "via": "speech"}, headers=headers).json()
    clicked = client.post(url, json={"decision": "approve", "via": "click"}, headers=headers).json()

    assert spoken["status"] == "awaiting_approval" and spoken["order"] is None
    assert clicked["status"] == "granted" and clicked["order"]["capability"] == "windows.app.close"


def test_the_user_can_deny_a_close(rig) -> None:
    client, headers, _, _ = rig
    asked = client.post("/v1/actions/proposals", json=CLOSE, headers=headers).json()

    denied = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "deny"}, headers=headers
    ).json()

    assert denied["status"] == "denied" and denied["speak"] == "Okay, I won't do that."


@pytest.mark.parametrize(
    "capability", ["finance.transfer", "finance.pay", "shell.run", "files.delete", "email.send"]
)
def test_forbidden_capabilities_are_refused_over_http(rig, capability: str) -> None:
    client, headers, _, _ = rig

    body = client.post(
        "/v1/actions/proposals",
        json={"capability": capability, "args": {"amount": 5}},
        headers=headers,
    ).json()

    assert body["status"] == "refused" and body["reason"] == "FORBIDDEN_CAPABILITY"
    assert body["order"] is None


def test_unknown_ids_are_404_and_bad_bodies_are_422(rig) -> None:
    client, headers, _, _ = rig

    assert client.get("/v1/actions/nope", headers=headers).status_code == 404
    assert (
        client.post(
            "/v1/actions/nope/approval", json={"decision": "approve"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post("/v1/actions/proposals", json={"capability": "x"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/actions/proposals", json={**OPEN, "tier": "T0"}, headers=headers
        ).status_code
        == 422
    )  # a proposal cannot name its own tier
    assert (
        client.post(
            "/v1/actions/some-id/approval", json={"decision": "maybe"}, headers=headers
        ).status_code
        == 422
    )


def test_the_ledger_is_written_without_the_argument_values_that_are_private(rig) -> None:
    client, headers, core, _ = rig
    body = client.post(
        "/v1/actions/proposals",
        json={
            "capability": "finance.add_transaction",
            "args": {
                "amount": 987.65,
                "currency": "USD",
                "category": "food",
                "note": "secret lunch",
            },
        },
        headers=headers,
    ).json()
    assert core.broker is not None

    rows = core.broker.ledger.rows(body["action_id"])  # type: ignore[attr-defined]

    text = json.dumps([r.payload for r in rows])
    assert "987.65" not in text and "secret lunch" not in text
    assert rows[0].kind == "proposed"


def test_the_public_key_file_is_written_for_the_executor_and_holds_no_private_key(rig) -> None:
    _, _, _, data_dir = rig

    text = (data_dir / "grant_public_key.pem").read_text(encoding="utf-8")

    assert text.startswith("-----BEGIN PUBLIC KEY-----") and "PRIVATE" not in text


def test_without_a_key_vault_the_routes_answer_503_not_a_fake_grant(tmp_path) -> None:
    core = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path)
    )  # real vault: unavailable in tests
    core.startup()
    try:
        client = TestClient(create_app(core))
        headers = {"Authorization": f"Bearer {core.local_token}"}

        response = client.post("/v1/actions/proposals", json=OPEN, headers=headers)

        assert core.broker is None
        assert response.status_code == 503 and response.json()["error"] == "actions_unavailable"
    finally:
        core.shutdown()
