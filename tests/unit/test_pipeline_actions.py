"""B3c: a voice turn announces actions to the app, and only an executor's report is spoken."""

from __future__ import annotations

import asyncio
from pathlib import Path

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.router import IntentRouter
from reva_core.policy.apps import AppCatalog
from reva_core.policy.broker import Broker
from reva_core.policy.grants import load_or_create_signer
from reva_core.policy.ledger import MemoryLedger
from reva_core.session.events import SessionEventKind
from tests.unit.test_turn_pipeline import NOW, Rig, collect


def wire(rig: Rig) -> Broker:
    catalog = AppCatalog()
    broker = Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
        app_keys=catalog.allowed_keys,
        app_names=catalog.display_names,
    )
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    rig.pipeline._router = IntentRouter(
        dialogue, broker, resolver=catalog.resolver, app_names=catalog.display_names
    )
    broker.subscribe(rig.pipeline.on_action_update)
    return broker


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_open_sends_the_signed_order_and_says_it_asked_not_that_it_opened(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "open notepad")
    broker = wire(rig)
    await rig.listening()

    await rig.talk()
    events = await collect(rig)

    proposed = next(e for e in events if e.kind == SessionEventKind.ACTION_PROPOSED)
    assert proposed.payload["capability"] == "windows.app.open"
    assert proposed.payload["order"]["args"] == {"app_key": "notepad"}
    assert proposed.payload["order"]["signature"]
    text = next(e for e in events if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL)
    assert text.payload["text"] == "Asking your PC to open Notepad."
    assert "avatar_event" not in text.payload  # nothing is verified yet
    assert broker.get(proposed.payload["action_id"]).status == "granted"


async def test_the_executor_report_is_what_gets_spoken_and_shown(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "open notepad")
    broker = wire(rig)
    await rig.listening()
    await rig.talk()
    events = await collect(rig)
    order = next(e for e in events if e.kind == SessionEventKind.ACTION_PROPOSED).payload["order"]
    await rig.pipeline.on_playback_finished()
    await collect(rig)

    broker.report(
        order["grant"]["action_id"],
        order["grant"]["grant_id"],
        "verified",
        {"kind": "process_started", "ref": "pid:44 window:0x10"},
    )
    await settle()
    await rig.pipeline.wait_idle()
    after = await collect(rig)

    outcome = next(e for e in after if e.kind == SessionEventKind.ACTION_OUTCOME)
    assert outcome.payload["status"] == "verified" and outcome.payload["speak"] == "Opened Notepad."
    said = next(e for e in after if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL)
    assert said.payload["text"] == "Opened Notepad." and said.payload["source"] == "template"
    assert said.payload["avatar_event"]["cause"] == "verified_outcome"
    assert said.payload["avatar_event"]["action_id"] == order["grant"]["action_id"]
    assert rig.tts.spoken[-1] == "Opened Notepad."


async def test_a_launch_with_no_window_is_spoken_as_unknown_and_the_face_stays_neutral(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "open notepad")
    broker = wire(rig)
    await rig.listening()
    await rig.talk()
    order = next(
        e for e in await collect(rig) if e.kind == SessionEventKind.ACTION_PROPOSED
    ).payload["order"]
    await rig.pipeline.on_playback_finished()
    await collect(rig)

    broker.report(
        order["grant"]["action_id"],
        order["grant"]["grant_id"],
        "verified",
        {"kind": "process_started", "ref": "pid:44 no_window"},
    )
    await settle()
    await rig.pipeline.wait_idle()
    after = await collect(rig)

    said = next(e for e in after if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL)
    assert said.payload["text"] == "I started it but couldn't confirm the window. Check Activity."
    assert (
        "avatar_event" not in said.payload
        or said.payload["avatar_event"]["cause"] != "verified_outcome"
    )


async def test_close_asks_for_a_click_and_the_card_event_carries_the_prompt(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "close spotify")
    broker = wire(rig)
    await rig.listening()

    await rig.talk()
    events = await collect(rig)

    card = next(e for e in events if e.kind == SessionEventKind.ACTION_APPROVAL_REQUIRED)
    assert card.payload["prompt"] == "Close Spotify? Approve it on screen."
    assert card.payload["order"] is None  # no grant until someone clicks
    assert not any(e.kind == SessionEventKind.ACTION_PROPOSED for e in events)
    assert broker.get(card.payload["action_id"]).status == "awaiting_approval"


async def test_another_sessions_actions_are_not_announced_here(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "open notepad")
    broker = wire(rig)
    other = Rig(tmp_path / "other" if (tmp_path / "other").mkdir() is None else tmp_path, "hi")
    broker.subscribe(other.pipeline.on_action_update)
    await rig.listening()
    await other.listening()
    await rig.talk()
    order = next(
        e for e in await collect(rig) if e.kind == SessionEventKind.ACTION_PROPOSED
    ).payload["order"]
    await collect(other)

    broker.report(
        order["grant"]["action_id"],
        order["grant"]["grant_id"],
        "failed",
        None,
    )
    await settle()

    assert not any(e.kind == SessionEventKind.ACTION_OUTCOME for e in await collect(other))
