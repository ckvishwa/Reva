"""B4-FIX: every free-text field is bounded at the API edge with the typed 422, never a 500.

The action ledger bounds what it stores (`test_queue_saturation.py`), but the bound that matters to
a caller is the one at the door: an over-long value is refused with `DOMAIN.VALIDATION` and the name
of the field, and nothing is recorded. Each field below is tried one character over its limit.
"""

from __future__ import annotations

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.orchestration.lifecycle import CoreLifecycle

OPEN = {"capability": "windows.app.open", "args": {"app_key": "notepad"}}


@pytest.fixture
def rig(tmp_path):
    from fastapi.testclient import TestClient

    from reva_core.api.app import create_app
    from reva_core.config.settings import load_settings

    core = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path, domain_keystore="memory"),
        grant_key_provider=InMemoryKeyProvider(),
        domain_key_provider=InMemoryKeyProvider(),
    )
    core.startup()
    client = TestClient(create_app(core), raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer {core.local_token}"})
    yield client, core
    core.shutdown()


def assert_typed_422(response, field: str | None = None) -> None:
    assert response.status_code == 422, (response.status_code, response.text[:200])
    body = response.json()
    assert body["code"] == "DOMAIN.VALIDATION" and body["error"] == "validation_error"
    if field:
        assert body.get("field") == field
    assert "x" * 50 not in response.text  # the offending value is never echoed back


def ledger_rows(core) -> int:
    return len(core.broker.ledger.recent(500))


PROPOSAL_CASES = [
    ("capability", {**OPEN, "capability": "c" * 101}),
    ("proposal_id", {**OPEN, "proposal_id": "p" * 65}),
    ("args", {**OPEN, "args": {"k" * 65: "x"}}),  # a key name too long
    ("args", {**OPEN, "args": {f"k{i}": "x" for i in range(33)}}),  # too many keys
    ("args", {**OPEN, "args": {"app_key": "x" * 20001}}),  # a value too long
    ("args", {**OPEN, "args": {"a": {"b": {"c": {"d": {"e": 1}}}}}}),  # nested too deep
    ("args", {**OPEN, "args": {"a": ["x" * 10_000] * 8}}),  # many large values together
    ("args", {**OPEN, "args": {"a": [1] * 5000}}),  # a very long list
]


@pytest.mark.parametrize(("field", "body"), PROPOSAL_CASES)
def test_an_oversized_proposal_field_is_a_typed_422_and_records_nothing(
    rig, field: str, body: dict
) -> None:
    client, core = rig
    before = ledger_rows(core)

    response = client.post("/v1/actions/proposals", json=body)

    assert_typed_422(response, field)
    assert ledger_rows(core) == before


def test_values_at_the_limit_are_still_accepted(rig) -> None:
    client, _ = rig

    ok = client.post(
        "/v1/actions/proposals",
        json={"capability": "memory.recall", "args": {"query": "q" * 500}},
    )
    forbidden_with_big_args = client.post(
        "/v1/actions/proposals",
        json={"capability": "finance.transfer", "args": {"request": "r" * 500}},
    )

    assert ok.status_code == 201
    assert forbidden_with_big_args.status_code == 201
    assert forbidden_with_big_args.json()["reason"] == "FORBIDDEN_CAPABILITY"


def test_a_forbidden_capability_with_huge_arguments_is_refused_at_the_door_not_logged(rig) -> None:
    client, core = rig
    before = ledger_rows(core)

    response = client.post(
        "/v1/actions/proposals",
        json={"capability": "shell.run", "args": {"command": "x" * 20_001}},
    )

    assert_typed_422(response, "args")
    assert ledger_rows(core) == before


def test_approval_and_outcome_text_fields_are_bounded(rig) -> None:
    client, _ = rig
    asked = client.post("/v1/actions/proposals", json=OPEN).json()
    action = asked["action_id"]
    grant = asked["order"]["grant"]["grant_id"]

    assert_typed_422(
        client.post(
            f"/v1/actions/{action}/approval", json={"decision": "approve", "via": "v" * 17}
        ),
        "via",
    )
    assert_typed_422(
        client.put(f"/v1/actions/{action}", json={"grant_id": "g" * 65, "status": "failed"}),
        "grant_id",
    )
    for field, value in (("kind", "k" * 65), ("ref", "r" * 201)):
        evidence = {"kind": "process_started", "ref": "pid:1 window:0x2", field: value}
        response = client.put(
            f"/v1/actions/{action}",
            json={"grant_id": grant, "status": "verified", "evidence": evidence},
        )
        assert_typed_422(response, field)
    assert client.get(f"/v1/actions/{action}").json()["status"] == "granted"  # untouched


def test_app_names_and_aliases_are_bounded_with_the_same_typed_error(rig) -> None:
    client, _ = rig
    client.put(
        "/v1/apps/discovered", json={"apps": [{"key": "obsidian", "display_name": "Obsidian"}]}
    )

    assert_typed_422(
        client.put(
            "/v1/apps/discovered", json={"apps": [{"key": "ok-app", "display_name": "n" * 61}]}
        ),
        "display_name",
    )
    assert_typed_422(
        client.put("/v1/apps/discovered", json={"apps": [{"key": "k" * 33, "display_name": "x"}]}),
        "key",
    )
    assert_typed_422(
        client.put("/v1/apps/obsidian", json={"display_name": "n" * 61, "aliases": []}),
        "display_name",
    )
    assert_typed_422(client.put("/v1/apps/obsidian", json={"aliases": ["a" * 41]}), "aliases")
    assert_typed_422(client.put("/v1/apps/obsidian", json={"aliases": ["ok"] * 9}), "aliases")


def test_a_bad_app_request_the_catalog_refuses_is_the_same_typed_error(rig) -> None:
    client, _ = rig

    never_found = client.put("/v1/apps/never-found", json={"aliases": []})
    built_in = client.delete("/v1/apps/spotify")

    for response in (never_found, built_in):
        assert response.status_code == 422
        assert response.json()["code"] == "DOMAIN.VALIDATION"
        assert response.json()["detail"]  # a sentence the Apps page can show


def test_session_and_telemetry_and_privacy_text_fields_are_bounded(rig) -> None:
    client, _ = rig

    assert_typed_422(client.post("/v1/voice/sessions", json={"device_id": "d" * 65}), "device_id")
    assert_typed_422(client.put("/v1/settings/telemetry", json={"enabled": "x" * 300}), "enabled")
    assert_typed_422(
        client.put("/v1/settings/privacy", json={"domains": {"d" * 5000: {"sync": True}}}),
        None,
    )


def test_a_huge_body_is_refused_without_a_500(rig) -> None:
    client, _ = rig

    response = client.post(
        "/v1/actions/proposals",
        content=b'{"capability":"windows.app.open","args":{"a":"' + b"x" * 2_000_000 + b'"}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code in (413, 422)
    assert response.json()["code"] in ("DOMAIN.VALIDATION", "CORE.VALIDATION")
