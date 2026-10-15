"""B3c: confirm card -> Kernel commit -> "Saved.", the apps allowlist and Activity over HTTP.

Needs the built Domain Kernel binding. In-memory key providers only: no real credentials.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reva_core.api.app import create_app
from reva_core.config.settings import load_settings
from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel
from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.orchestration.lifecycle import CoreLifecycle

try:
    load_kernel()
except KernelUnavailableError as exc:
    pytest.skip(f"Domain Kernel binding not built: {exc}", allow_module_level=True)

EXPENSE = {
    "capability": "finance.add_transaction",
    "args": {"amount": 12, "currency": "USD", "category": "Food · Dining", "note": "lunch"},
}


@pytest.fixture
def rig(tmp_path):
    core = CoreLifecycle(
        load_settings(_env_file=None, data_dir=tmp_path, domain_keystore="memory"),
        grant_key_provider=InMemoryKeyProvider(),
        domain_key_provider=InMemoryKeyProvider(),
    )
    core.startup()
    client = TestClient(create_app(core))
    client.headers.update({"Authorization": f"Bearer {core.local_token}"})
    yield client, core
    core.shutdown()


def _account(client) -> None:
    body = {"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 0}
    assert client.post("/v1/domains/finance/accounts", json=body).status_code == 201


def test_the_confirm_card_waits_and_a_spoken_yes_never_commits(rig) -> None:
    client, _ = rig
    _account(client)

    asked = client.post("/v1/actions/proposals", json=EXPENSE).json()
    spoken = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "approve", "via": "speech"}
    ).json()

    assert asked["status"] == "awaiting_approval"
    assert asked["prompt"] == "Add $12.00 for Food · Dining? Confirm on screen."
    assert spoken["status"] == "awaiting_approval"
    assert client.get("/v1/domains/finance/transactions").json()["items"] == []


def test_click_confirm_commits_through_the_kernel_and_only_then_says_saved(rig) -> None:
    client, _ = rig
    _account(client)
    asked = client.post("/v1/actions/proposals", json=EXPENSE).json()

    done = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "approve", "via": "click"}
    ).json()

    assert done["status"] == "verified" and done["speak"] == "Saved."
    assert done["order"] is None  # the Kernel executor ran in Core; nothing is handed out
    items = client.get("/v1/domains/finance/transactions").json()["items"]
    assert len(items) == 1 and items[0]["amount_minor"] == -1200
    assert items[0]["description"] == "lunch"
    activity = client.get("/v1/activity").json()["items"][0]
    assert activity["result"] == "Done (confirmed)" and activity["request"] == "Add an expense"
    assert activity["evidence"]


def test_without_an_account_nothing_is_saved_and_it_does_not_say_saved(rig) -> None:
    client, _ = rig
    asked = client.post("/v1/actions/proposals", json=EXPENSE).json()

    done = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "approve", "via": "click"}
    ).json()

    assert done["status"] == "failed" and done["speak"] == "That didn't work. Nothing was changed."
    assert client.get("/v1/domains/finance/transactions").json()["items"] == []


def test_deny_on_the_card_saves_nothing(rig) -> None:
    client, _ = rig
    _account(client)
    asked = client.post("/v1/actions/proposals", json=EXPENSE).json()

    denied = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "deny"}
    ).json()

    assert denied["status"] == "denied"
    assert client.get("/v1/domains/finance/transactions").json()["items"] == []


def test_apps_discovery_approval_and_use_over_http(rig) -> None:
    client, _ = rig

    listed = client.get("/v1/apps").json()
    assert {a["key"] for a in listed["apps"]} == {
        "notepad",
        "calculator",
        "chrome",
        "vscode",
        "spotify",
    }
    found = client.put(
        "/v1/apps/discovered",
        json={"apps": [{"key": "obsidian", "display_name": "Obsidian"}]},
    ).json()
    assert found["waiting"] == [{"key": "obsidian", "display_name": "Obsidian"}]
    before = client.post(
        "/v1/actions/proposals",
        json={"capability": "windows.app.open", "args": {"app_key": "obsidian"}},
    ).json()
    approved = client.put("/v1/apps/obsidian", json={"aliases": ["second brain"]}).json()
    after = client.post(
        "/v1/actions/proposals",
        json={"capability": "windows.app.open", "args": {"app_key": "obsidian"}},
    ).json()

    assert before["status"] == "refused" and before["reason"] == "INVALID_ARGS"
    assert any(a["key"] == "obsidian" and "second brain" in a["aliases"] for a in approved["apps"])
    assert approved["waiting"] == []
    assert after["status"] == "granted" and after["order"]["args"] == {"app_key": "obsidian"}


def test_bad_app_requests_are_422(rig) -> None:
    client, _ = rig

    assert client.put("/v1/apps/never-found", json={"aliases": []}).status_code == 422
    assert client.put("/v1/apps/notepad", json={"aliases": []}).status_code == 422
    assert client.delete("/v1/apps/spotify").status_code == 422
    assert client.put("/v1/apps/discovered", json={"apps": [], "extra": 1}).status_code == 422
    assert client.get("/v1/activity", params={"limit": 0}).status_code == 422
