"""B3c: app catalog, approved apps reaching authorize(), evidence shapes (AR-WIN-005..009)."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language import outcomes
from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.router import IntentRouter
from reva_core.policy import activity
from reva_core.policy.apps import AppCatalog, AppCatalogError
from reva_core.policy.authorize import Proposal
from reva_core.policy.broker import Broker
from reva_core.policy.grants import load_or_create_signer
from reva_core.policy.ledger import MemoryLedger

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def catalog_with_obsidian(path: Path | None = None) -> AppCatalog:
    catalog = AppCatalog(path)
    catalog.report_discovered([("obsidian", "Obsidian"), ("slack", "Slack")])
    return catalog


def broker_for(catalog: AppCatalog) -> Broker:
    return Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
        app_keys=catalog.allowed_keys,
        app_names=catalog.display_names,
    )


# ----------------------------------------------------------------------- catalog


def test_discovered_apps_wait_and_are_not_allowed_until_approved() -> None:
    catalog = catalog_with_obsidian()

    assert [k for k, _ in catalog.waiting()] == ["obsidian", "slack"]
    assert "obsidian" not in catalog.allowed_keys()
    approved = catalog.approve("obsidian", None, ["my notes", "second brain"])

    assert approved.display_name == "Obsidian"
    assert approved.aliases == ("obsidian", "my notes", "second brain")
    assert "obsidian" in catalog.allowed_keys() and [k for k, _ in catalog.waiting()] == ["slack"]


def test_an_app_that_was_never_discovered_cannot_be_approved() -> None:
    with pytest.raises(AppCatalogError, match="not found"):
        AppCatalog().approve("photoshop", "Photoshop", [])


@pytest.mark.parametrize(
    "alias",
    ["the", "app please", "calc", "vs code", "x" * 50, "bad;name"],
)
def test_bad_or_clashing_spoken_names_are_refused(alias: str) -> None:
    catalog = catalog_with_obsidian()

    with pytest.raises(AppCatalogError):
        catalog.approve("obsidian", None, [alias])


def test_a_name_that_belongs_to_another_approved_app_is_refused() -> None:
    catalog = catalog_with_obsidian()
    catalog.approve("obsidian", None, ["notes"])

    with pytest.raises(AppCatalogError, match="already belongs"):
        catalog.approve("slack", None, ["notes"])


def test_built_in_apps_cannot_be_replaced_or_removed() -> None:
    catalog = catalog_with_obsidian()

    with pytest.raises(AppCatalogError):
        catalog.approve("notepad", "Evil Notepad", ["notepad"])
    with pytest.raises(AppCatalogError):
        catalog.remove("spotify")
    catalog.report_discovered([("notepad", "Notepad Clone")])
    assert "notepad" not in dict(catalog.waiting())


def test_keys_must_look_like_keys() -> None:
    catalog = AppCatalog()
    catalog.report_discovered([("Bad Key", "x"), ("../etc", "x"), ("a", "x"), ("ok-app", "OK")])

    assert dict(catalog.waiting()) == {"ok-app": "OK"}


def test_the_catalog_persists_and_a_damaged_file_means_nothing_approved(tmp_path: Path) -> None:
    path = tmp_path / "apps.json"
    first = catalog_with_obsidian(path)
    first.approve("obsidian", "Obsidian", ["journal"])

    again = AppCatalog(path)
    assert "obsidian" in again.allowed_keys() and "slack" in dict(again.waiting())
    path.write_text("{ not json", encoding="utf-8")
    assert "obsidian" not in AppCatalog(path).allowed_keys()
    assert "launch" not in path.read_text(encoding="utf-8").replace("{ not json", "")


def test_the_file_holds_no_launch_targets(tmp_path: Path) -> None:
    path = tmp_path / "apps.json"
    catalog_with_obsidian(path).approve("obsidian", None, [])

    text = path.read_text(encoding="utf-8").lower()

    assert "exe" not in text and "\\\\" not in text and "path" not in text


# --------------------------------------------------------------- authorize + router


def test_an_approved_app_can_be_opened_and_an_unapproved_one_cannot() -> None:
    catalog = catalog_with_obsidian()
    broker = broker_for(catalog)
    ask = Proposal("act-00000001", "windows.app.open", {"app_key": "obsidian"})
    before = broker.propose(ask)
    catalog.approve("obsidian", None, [])
    after = broker.propose(Proposal("act-00000002", "windows.app.open", {"app_key": "obsidian"}))

    assert before.reason == "INVALID_ARGS" and before.order is None
    assert after.status == "granted" and after.order is not None
    assert (
        broker.propose(Proposal("act-00000003", "windows.app.open", {"app_key": "slack"})).reason
        == "INVALID_ARGS"
    )


def test_the_spoken_alias_of_an_approved_app_opens_it_and_the_reply_uses_its_name() -> None:
    catalog = catalog_with_obsidian()
    catalog.approve("obsidian", "Obsidian", ["second brain"])
    broker = broker_for(catalog)
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    router = IntentRouter(
        dialogue, broker, resolver=catalog.resolver, app_names=catalog.display_names
    )

    turn = router.route("open my second brain", now=NOW)

    assert turn.kind == "chat" or turn.kind == "action"
    opened = router.route("open second brain", now=NOW)
    assert opened.kind == "action" and opened.reply == "Asking your PC to open Obsidian."
    assert opened.action is not None and opened.action.order is not None
    assert opened.action.order.args == {"app_key": "obsidian"}
    done = broker.report(
        opened.action.action_id,
        opened.action.order.grant.grant_id,
        "verified",
        {"kind": "process_started", "ref": "pid:12 window:0xAB"},
    )
    assert done.speak == "Opened Obsidian."


# ------------------------------------------------------- evidence needs a real window


@pytest.mark.parametrize(
    "ref",
    [
        "pid:4242",  # process only: no window
        "pid:4242 window:",
        "pid:4242 window:none",
        "window:0x1",
        "pid:abc window:0x1",
        "pid:1 window:0x1; calc.exe",
        "opened ok",
        "pid:4242 no_window",
    ],
)
def test_a_launch_without_a_window_never_reads_as_opened(ref: str) -> None:
    broker = broker_for(AppCatalog())
    view = broker.propose(Proposal("act-00000010", "windows.app.open", {"app_key": "notepad"}))
    assert view.order is not None

    done = broker.report(
        view.action_id,
        view.order.grant.grant_id,
        "verified",
        {"kind": "process_started", "ref": ref},
    )

    assert done.status == "unknown"
    assert done.speak == "I started it but couldn't confirm the window. Check Activity."


def test_close_is_verified_only_when_the_process_is_gone() -> None:
    broker = broker_for(AppCatalog())
    asked = broker.propose(Proposal("act-00000011", "windows.app.close", {"app_key": "spotify"}))
    approved = broker.approve(asked.action_id, via="click", device="local")
    assert approved.order is not None
    grant = approved.order.grant.grant_id

    still_there = broker.report(
        asked.action_id, grant, "verified", {"kind": "process_exited", "ref": "pid:77 running"}
    )
    assert still_there.status == "unknown" and still_there.speak == outcomes.CLOSE_UNKNOWN


def test_close_with_the_process_gone_says_closed() -> None:
    broker = broker_for(AppCatalog())
    asked = broker.propose(Proposal("act-00000012", "windows.app.close", {"app_key": "spotify"}))
    approved = broker.approve(asked.action_id, via="click", device="local")
    assert approved.order is not None

    done = broker.report(
        asked.action_id,
        approved.order.grant.grant_id,
        "verified",
        {"kind": "process_exited", "ref": "pids:77,78 exited"},
    )

    assert done.status == "verified" and done.speak == "Closed Spotify."


def test_false_success_corpus_for_launches_0_of_100() -> None:
    """A launch that never shows a window must read unknown, never verified (B3c bar: 0/100)."""
    rng = random.Random(7)  # noqa: S311 - test data, not security
    wrong = 0
    for index in range(100):
        broker = broker_for(AppCatalog())
        view = broker.propose(
            Proposal(
                f"act-{index:08d}",
                "windows.app.open",
                {"app_key": rng.choice(["notepad", "chrome"])},
            )
        )
        assert view.order is not None
        kind = rng.choice(["no_window", "process_only", "wrong_kind", "empty", "none"])
        evidence = {
            "no_window": {
                "kind": "process_started",
                "ref": f"pid:{rng.randint(1, 99999)} no_window",
            },
            "process_only": {"kind": "process_started", "ref": f"pid:{rng.randint(1, 99999)}"},
            "wrong_kind": {"kind": "kernel_event", "ref": "evt-12345678"},
            "empty": {},
            "none": None,
        }[kind]
        done = broker.report(view.action_id, view.order.grant.grant_id, "verified", evidence)
        if done.status == "verified" or "opened" in (done.speak or "").lower().split():
            wrong += 1

    assert wrong == 0


# ------------------------------------------------------------------------ activity


def test_activity_lists_each_action_with_its_result_and_evidence_but_no_private_values() -> None:
    catalog = AppCatalog()
    broker = broker_for(catalog)
    opened = broker.propose(
        Proposal("act-00000020", "windows.app.open", {"app_key": "notepad"}, source="voice")
    )
    assert opened.order is not None
    broker.report(
        opened.action_id,
        opened.order.grant.grant_id,
        "verified",
        {"kind": "process_started", "ref": "pid:5 window:0x9"},
    )
    broker.propose(Proposal("act-00000021", "windows.app.close", {"app_key": "chrome"}))
    broker.propose(
        Proposal(
            "act-00000022", "finance.transfer", {"amount": 999, "note": "rent"}, source="voice"
        )
    )
    expense = broker.propose(
        Proposal(
            "act-00000023",
            "finance.add_transaction",
            {"amount": 87.65, "currency": "USD", "category": "Food", "note": "secret lunch"},
        )
    )
    assert expense.status == "awaiting_approval"

    rows = {r["action_id"]: r for r in activity.recent(broker.ledger, catalog.display_names())}

    assert rows["act-00000020"]["request"] == "Open Notepad"
    assert rows["act-00000020"]["from"] == "Voice"
    assert rows["act-00000020"]["result"] == "Done (confirmed)"
    assert rows["act-00000020"]["evidence"] == "pid:5 window:0x9"
    assert rows["act-00000021"]["result"] == "Waiting for your approval"
    assert rows["act-00000022"]["result"] == "Refused (forbidden capability)"
    text = json.dumps(list(rows.values()))
    assert "87.65" not in text and "secret lunch" not in text and "999" not in text
