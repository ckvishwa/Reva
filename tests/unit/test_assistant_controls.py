"""B3d: assistant.stop and assistant.repeat (T0) and assistant.undo (confirmed T2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language import outcomes
from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.entities import AppResolver
from reva_core.language.router import IntentRouter
from reva_core.language.rules import parse
from reva_core.policy.authorize import AuthState, Proposal, authorize
from reva_core.policy.broker import ActionView, Broker
from reva_core.policy.grants import load_or_create_signer
from reva_core.policy.ledger import MemoryLedger
from reva_core.policy.registry import DEFAULT_REGISTRY, Tier
from reva_core.session.events import SessionEventKind
from reva_core.session.state import SessionState
from tests.unit.test_turn_pipeline import Rig, collect

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
RESOLVER = AppResolver(("notepad", "calculator", "chrome", "vscode", "spotify"))
UNDO_CARD = "Undo the last expense? Confirm on screen."


def rig(*, undoable: bool = True) -> tuple[IntentRouter, Broker, DialogueTracker]:
    broker = Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
    )
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    router = IntentRouter(dialogue, broker, can_undo=lambda _id: undoable)
    return router, broker, dialogue


def as_view(base: ActionView, status: str, capability: str | None = None) -> ActionView:
    return replace(base, status=status, capability=capability or base.capability)


# ------------------------------------------------------------------ registry and authorize


def test_the_three_capabilities_have_the_deliberate_tiers() -> None:
    stop = DEFAULT_REGISTRY.get("assistant.stop")
    repeat = DEFAULT_REGISTRY.get("assistant.repeat")
    undo = DEFAULT_REGISTRY.get("assistant.undo")

    assert stop is not None and stop.tier == Tier.T0 and stop.evidence_kind == "none"
    assert repeat is not None and repeat.tier == Tier.T0 and repeat.evidence_kind == "none"
    assert undo is not None and undo.tier == Tier.T2 and undo.confirm_on == "origin"
    assert undo.evidence_kind == "kernel_event" and not undo.idempotent


def test_undo_without_a_click_is_refused_by_authorize() -> None:
    proposal = Proposal(
        proposal_id="p-1",
        capability="assistant.undo",
        args={"target_action_id": "a-1"},
        source="voice",
        origin_device="local",
        target_device="local",
    )

    decision = authorize(proposal, AuthState(now=NOW), DEFAULT_REGISTRY)

    assert not decision.allowed and decision.reason == "APPROVAL_REQUIRED"


# ------------------------------------------------------------------ rules


@pytest.mark.parametrize(
    ("text", "capability"),
    [
        ("stop", "assistant.stop"),
        ("Stop talking.", "assistant.stop"),
        ("please stop", "assistant.stop"),
        ("be quiet", "assistant.stop"),
        ("repeat that", "assistant.repeat"),
        ("say that again", "assistant.repeat"),
        ("what did you say?", "assistant.repeat"),
        ("undo", "assistant.undo"),
        ("undo that", "assistant.undo"),
        ("undo the last expense", "assistant.undo"),
        ("take that back", "assistant.undo"),
    ],
)
def test_control_phrases_parse(text: str, capability: str) -> None:
    hit = parse(text, RESOLVER)
    assert hit is not None and hit.capability == capability and hit.args == {}


@pytest.mark.parametrize(
    "text",
    [
        "stop the music",
        "do not stop believing",
        "stop by the shop and buy milk",
        "undo my commit in the repo",
        "repeat after me hello",
        "what did you say about the budget",
        "stopwatch",
    ],
)
def test_longer_sentences_are_not_controls(text: str) -> None:
    hit = parse(text, RESOLVER)
    assert hit is None or not hit.capability.startswith("assistant.")


# ------------------------------------------------------------------ router


def test_stop_drops_a_draft_and_goes_through_the_broker() -> None:
    router, _, _ = rig()
    router.route("add twelve dollars for lunch", now=NOW)
    assert router.pending is not None

    turn = router.route("stop", now=NOW)

    assert turn.kind == "stop" and turn.reply is None
    assert router.pending is None
    assert turn.action is not None and turn.action.capability == "assistant.stop"
    assert turn.action.status == "allowed" and turn.action.speak is None
    assert router.route("yes", now=NOW).kind == "chat"  # the draft is gone: nothing to confirm


def test_stop_cancels_a_guess_and_an_amount_question() -> None:
    router, _, _ = rig()
    router.route("open spotfy", now=NOW)

    assert router.route("stop", now=NOW).kind == "stop"
    assert router.route("yes", now=NOW).kind == "chat"

    router.route("add twelve fifty for lunch", now=NOW)
    assert router.route("stop", now=NOW).kind == "stop"
    assert router.route("the first one", now=NOW).kind not in ("amended", "proposed")


def test_stop_works_without_a_broker() -> None:
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    router = IntentRouter(dialogue)

    turn = router.route("stop", now=NOW)

    assert turn.kind == "stop" and turn.action is None


def test_repeat_is_a_t0_decision_and_leaves_the_words_to_the_pipeline() -> None:
    router, _, _ = rig()

    turn = router.route("repeat that", now=NOW)

    assert turn.kind == "repeat" and turn.reply is None
    assert turn.action is not None and turn.action.tier == "T0"


def test_undo_proposes_a_t2_card_bound_to_the_newest_committed_expense() -> None:
    router, broker, dialogue = rig()
    dialogue.record_commit("action-0001")

    turn = router.route("undo that", now=NOW)

    assert turn.kind == "approval" and turn.reply == UNDO_CARD
    assert turn.action is not None and turn.action.status == "awaiting_approval"
    assert turn.action.capability == "assistant.undo" and turn.action.tier == "T2"
    assert turn.action.order is None  # no grant until a click
    proposal = broker._records[turn.action.action_id].proposal  # noqa: SLF001
    assert dict(proposal.args) == {"target_action_id": "action-0001"}


def test_a_spoken_yes_never_approves_an_undo() -> None:
    router, broker, dialogue = rig()
    dialogue.record_commit("action-0001")
    asked = router.route("undo", now=NOW)
    assert asked.action is not None

    router.route("yes", now=NOW)
    spoken = broker.approve(asked.action.action_id, via="speech", device="local")

    assert spoken.status == "awaiting_approval" and spoken.order is None


def test_undo_with_nothing_committed_says_so_and_proposes_nothing() -> None:
    router, broker, _ = rig()

    turn = router.route("undo", now=NOW)

    assert turn.kind == "unresolved" and turn.reply == outcomes.NOTHING_TO_UNDO
    assert broker.ledger.recent(10) == []


def test_undo_of_an_expense_the_executor_no_longer_holds_is_not_proposed() -> None:
    router, broker, dialogue = rig(undoable=False)
    dialogue.record_commit("action-0001")

    turn = router.route("undo", now=NOW)

    assert turn.reply == outcomes.NOTHING_TO_UNDO and broker.ledger.recent(10) == []


def test_only_a_verified_expense_sets_the_undo_pointer_and_only_a_verified_undo_moves_it() -> None:
    router, _, dialogue = rig()
    router.route("add twelve dollars for lunch", now=NOW)
    asked = router.route("yes", now=NOW)
    assert asked.kind == "approval" and asked.action is not None
    assert dialogue.undo_target() is None  # the card has not been clicked

    for status in ("denied", "failed", "unknown"):
        router.note_outcome(as_view(asked.action, status))
        assert dialogue.undo_target() is None
    router.note_outcome(as_view(asked.action, "verified"))
    assert dialogue.undo_target() == asked.action.action_id

    router.note_outcome(as_view(asked.action, "unknown", "assistant.undo"))
    assert dialogue.undo_target() == asked.action.action_id
    router.note_outcome(as_view(asked.action, "verified", "assistant.undo"))
    assert dialogue.undo_target() is None


# ------------------------------------------------------------------ templates and evidence


def test_undone_is_said_only_for_a_verified_undo() -> None:
    assert outcomes.outcome_text("verified", "assistant.undo", {}) == "Undone."
    for status in ("failed", "unknown", "denied", "attempted", "observed"):
        text = outcomes.outcome_text(status, "assistant.undo", {}).lower()
        assert not any(word in text for word in outcomes.SUCCESS_WORDS), (status, text)


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {"kind": "process_exited", "ref": "pid:4 exited"},
        {"kind": "kernel_event", "ref": "ok"},
        {"kind": "kernel_event", "ref": ""},
    ],
)
def test_a_verified_undo_without_kernel_evidence_is_unknown_never_undone(evidence) -> None:
    router, broker, dialogue = rig()
    dialogue.record_commit("action-0001")
    asked = router.route("undo", now=NOW)
    assert asked.action is not None
    granted = broker.approve(asked.action.action_id, via="click", device="local")
    assert granted.status == "granted" and granted.order is not None

    reported = broker.report(
        asked.action.action_id, granted.order.grant.grant_id, "verified", evidence
    )

    assert reported.status == "unknown" and reported.speak == outcomes.UNKNOWN
    assert "undone" not in (reported.speak or "").lower()


# ------------------------------------------------------------------ pipeline


async def test_stop_says_nothing_and_goes_back_to_listening(tmp_path: Path) -> None:
    rig_ = Rig(tmp_path, "stop")
    await rig_.listening()

    await rig_.talk()
    events = await collect(rig_)

    assert rig_.session.state == SessionState.LISTENING
    assert not any(e.kind == SessionEventKind.TTS_STARTED for e in events)
    assert not any(e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL for e in events)
    states = [e.payload["state"] for e in events if e.kind == SessionEventKind.SESSION_STATE]
    assert "speaking" not in states  # no speaking pose for a reply that is never spoken
    assert rig_.tts.spoken == [] and rig_.asked == []


async def test_repeat_says_the_last_words_again_and_nothing_new(tmp_path: Path) -> None:
    rig_ = Rig(tmp_path, "add twelve dollars for lunch", "repeat that")
    await rig_.listening()
    await rig_.talk()
    await rig_.pipeline.on_playback_finished()

    await rig_.talk()
    events = await collect(rig_)

    said = [e.payload["text"] for e in events if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL]
    assert said[-1] == "Add $12.00 for lunch? Say yes to confirm."
    assert rig_.tts.spoken == ["Add $12.00 for lunch? Say yes to confirm."] * 2
    assert rig_.asked == []


async def test_repeat_with_nothing_said_yet_claims_nothing(tmp_path: Path) -> None:
    rig_ = Rig(tmp_path, "say that again")
    await rig_.listening()

    await rig_.talk()
    events = await collect(rig_)

    said = [e.payload["text"] for e in events if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL]
    assert said == [outcomes.NOTHING_TO_REPEAT]
