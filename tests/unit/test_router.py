"""B1.3: the router drafts an expense, resolves "it" through the dialogue state, never commits."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.router import IntentRouter

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def make() -> tuple[IntentRouter, DialogueTracker]:
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    return IntentRouter(dialogue), dialogue


def test_add_twelve_dollars_for_lunch_then_make_it_fifteen() -> None:
    router, dialogue = make()

    first = router.route("add twelve dollars for lunch", now=NOW)
    second = router.route("make it fifteen", now=NOW)

    assert first.kind == "proposed" and first.proposal is not None
    assert first.proposal.amount_minor == 1200 and first.proposal.description == "lunch"
    assert first.reply == "Add $12.00 for lunch? Say yes to confirm."
    assert second.kind == "amended" and second.proposal is not None
    assert second.proposal.amount_minor == 1500 and second.proposal.description == "lunch"
    assert second.proposal.action_id == first.proposal.action_id  # same draft, not a new one
    assert second.reply == "Changed to $15.00 for lunch. Say yes to confirm."
    assert dialogue.resolve_reference("it").entity.id == first.proposal.action_id  # type: ignore[union-attr]


def test_accepting_calls_accept_proposal_and_never_claims_it_was_saved() -> None:
    router, dialogue = make()
    drafted = router.route("add 12 bucks for coffee", now=NOW)

    accepted = router.route("yes", now=NOW)

    assert accepted.kind == "accepted"
    assert dialogue.undo_target() == drafted.proposal.action_id  # type: ignore[union-attr]
    assert "Nothing is saved" in (accepted.reply or "")
    for word in ("saved it", "done", "added"):
        assert word not in (accepted.reply or "").lower()
    assert router.pending is None


def test_no_drops_the_draft() -> None:
    router, _ = make()
    router.route("add twelve dollars for lunch", now=NOW)

    assert router.route("never mind", now=NOW).kind == "dismissed"
    assert router.pending is None
    assert router.route("make it fifteen", now=NOW).kind == "unresolved"


def test_make_it_with_nothing_to_point_at_is_unresolved_not_a_guess() -> None:
    router, _ = make()

    turn = router.route("make it fifteen", now=NOW)

    assert turn.kind == "unresolved" and router.pending is None


def test_an_ambiguous_amount_is_asked_about_then_answered() -> None:
    router, _ = make()

    asked = router.route("add twelve fifty for lunch", now=NOW)
    answered = router.route("the first one", now=NOW)

    assert asked.kind == "clarify" and "$12.50" in (asked.reply or "")
    assert router.pending is not None and router.pending.amount_minor == 1250
    assert answered.kind == "proposed"


def test_a_new_ambiguous_draft_is_not_treated_as_an_amendment() -> None:
    router, _ = make()
    first = router.route("add twelve dollars for lunch", now=NOW)
    router.route("add twelve fifty for dinner", now=NOW)

    answered = router.route("the first one", now=NOW)

    assert answered.kind == "proposed"
    assert answered.proposal.action_id != first.proposal.action_id  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "text",
    [
        "what is the weather",
        "add some milk to the list",
        "",
        "tell me a joke",
        "yes",  # nothing to confirm
        "add twelve dollars",  # no description: asks, does not guess
    ],
)
def test_other_speech_is_not_a_draft(text: str) -> None:
    router, _ = make()

    turn = router.route(text, now=NOW)

    assert turn.proposal is None and router.pending is None
    assert turn.kind in ("chat", "clarify")


def test_the_description_is_sanitised_and_bounded() -> None:
    router, _ = make()

    turn = router.route("add 5 dollars for <script>alert(1)</script> " + "x" * 200, now=NOW)

    if turn.proposal is not None:
        assert len(turn.proposal.description) <= 40
        assert "<" not in turn.proposal.description
