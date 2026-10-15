"""B3d: `assistant.undo` is a confirmed T2 reversal through the Kernel's tombstone event.

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
    client.post(
        "/v1/domains/finance/accounts",
        json={"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 0},
    )
    yield client, core
    core.shutdown()


def _approve(client, action_id: str, via: str = "click") -> dict:
    return client.post(
        f"/v1/actions/{action_id}/approval", json={"decision": "approve", "via": via}
    ).json()


def _saved(client) -> str:
    asked = client.post("/v1/actions/proposals", json=EXPENSE).json()
    assert _approve(client, asked["action_id"])["status"] == "verified"
    return asked["action_id"]


def _undo(client, target: str) -> dict:
    return client.post(
        "/v1/actions/proposals",
        json={"capability": "assistant.undo", "args": {"target_action_id": target}},
    ).json()


def _items(client) -> list[dict]:
    return client.get("/v1/domains/finance/transactions").json()["items"]


def test_undo_waits_for_a_click_and_nothing_changes_before_it(rig) -> None:
    client, _ = rig
    saved = _saved(client)

    asked = _undo(client, saved)
    spoken = _approve(client, asked["action_id"], via="speech")

    assert asked["status"] == "awaiting_approval" and asked["tier"] == "T2"
    assert asked["prompt"] == "Undo the last expense? Confirm on screen."
    assert spoken["status"] == "awaiting_approval"
    assert len(_items(client)) == 1


def test_a_click_reverses_the_expense_and_only_the_kernel_event_says_undone(rig) -> None:
    client, _ = rig
    saved = _saved(client)
    asked = _undo(client, saved)

    done = _approve(client, asked["action_id"])

    assert done["status"] == "verified" and done["speak"] == "Undone."
    assert done["evidence_kind"] == "kernel_event"
    assert _items(client) == []
    activity = client.get("/v1/activity").json()["items"][0]
    assert activity["request"] == "Undo the last expense"
    assert activity["result"] == "Done (confirmed)" and activity["evidence"]


def test_undoing_twice_fails_and_says_nothing_was_changed(rig) -> None:
    client, _ = rig
    saved = _saved(client)
    _approve(client, _undo(client, saved)["action_id"])

    second = _approve(client, _undo(client, saved)["action_id"])

    assert second["status"] == "failed"
    assert second["speak"] == "That didn't work. Nothing was changed."


def test_an_unknown_target_fails_and_touches_nothing(rig) -> None:
    client, _ = rig
    _saved(client)

    done = _approve(client, _undo(client, "no-such-action")["action_id"])

    assert done["status"] == "failed" and len(_items(client)) == 1


def test_a_target_that_was_never_saved_cannot_be_undone(rig) -> None:
    client, _ = rig
    waiting = client.post("/v1/actions/proposals", json=EXPENSE).json()
    assert waiting["status"] == "awaiting_approval"

    done = _approve(client, _undo(client, waiting["action_id"])["action_id"])

    assert done["status"] == "failed"
    assert _items(client) == []


def test_deny_on_the_card_keeps_the_expense(rig) -> None:
    client, _ = rig
    saved = _saved(client)
    asked = _undo(client, saved)

    denied = client.post(
        f"/v1/actions/{asked['action_id']}/approval", json={"decision": "deny"}
    ).json()

    assert denied["status"] == "denied" and len(_items(client)) == 1


def test_arguments_are_checked_before_anything_is_asked(rig) -> None:
    client, _ = rig
    for args in (
        {},
        {"target_action_id": ""},
        {"target_action_id": "x" * 65},
        {"target_action_id": "a", "transaction_id": "b"},
    ):
        refused = client.post(
            "/v1/actions/proposals", json={"capability": "assistant.undo", "args": args}
        ).json()
        assert refused["status"] == "refused" and refused["reason"] == "INVALID_ARGS"


def test_only_the_newest_expense_can_be_undone_so_the_card_never_misnames_it(rig) -> None:
    client, _ = rig
    first = _saved(client)
    second = _saved(client)

    older = _approve(client, _undo(client, first)["action_id"])
    assert older["status"] == "failed" and len(_items(client)) == 2

    newest = _approve(client, _undo(client, second)["action_id"])
    assert newest["status"] == "verified" and len(_items(client)) == 1

    now_newest = _approve(client, _undo(client, first)["action_id"])
    assert now_newest["status"] == "verified" and _items(client) == []
