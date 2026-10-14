"""S06: the dialogue state tracker (AR-LANG-005, ARD-450 §3.4): persistence, anaphora, undo."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reva_core.language.dialogue import (
    MAX_FILE_BYTES,
    MAX_LABEL,
    MAX_REFERENCES,
    DialogueTracker,
    Entity,
    FileDialogueStore,
    MemoryDialogueStore,
    Option,
)

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def tx(ident: str, label: str = "Lunch") -> Entity:
    return Entity(ident, "transaction", label)


def tracker(store=None, clock: Clock | None = None, device: str = "device-0001") -> DialogueTracker:
    return DialogueTracker(device, store or MemoryDialogueStore(), clock=clock or Clock())


# ----------------------------------------------------------------------- anaphora


@pytest.mark.parametrize("phrase", ["it", "that", "that one", "this one", "the last one", "It."])
def test_it_and_that_one_mean_what_was_just_talked_about(phrase: str) -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1", "Coffee"))
    dialogue.reference(tx("tx-2", "Lunch"))

    reference = dialogue.resolve_reference(phrase)

    assert reference.status == "resolved" and reference.entity == tx("tx-2", "Lunch")


@pytest.mark.parametrize("phrase", ["the one before", "the previous one", "the one before that"])
def test_the_one_before_is_the_entity_before_that(phrase: str) -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1", "Coffee"))
    dialogue.reference(tx("tx-2", "Lunch"))

    assert dialogue.resolve_reference(phrase).entity == tx("tx-1", "Coffee")


def test_with_nothing_to_point_at_it_is_unresolved_never_guessed() -> None:
    dialogue = tracker()

    for phrase in ("it", "that one", "the last one", "the one before", "the last transaction"):
        assert dialogue.resolve_reference(phrase).status == "unresolved", phrase


def test_the_one_before_needs_two_things() -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1"))

    assert dialogue.resolve_reference("the one before").status == "unresolved"


def test_the_last_transaction_picks_the_latest_of_that_kind() -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1", "Coffee"))
    dialogue.reference(Entity("acct-1", "account", "Checking"))

    assert dialogue.resolve_reference("the last transaction").entity == tx("tx-1", "Coffee")
    assert dialogue.resolve_reference("the last account").entity.id == "acct-1"  # type: ignore[union-attr]
    assert dialogue.resolve_reference("the last reminder").status == "unresolved"


def test_mentioning_something_again_moves_it_to_the_front_without_duplicating() -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1"))
    dialogue.reference(tx("tx-2"))
    dialogue.reference(tx("tx-1"))

    assert [e.id for e in dialogue.state.last_referenced] == ["tx-1", "tx-2"]


def test_the_reference_list_and_labels_are_bounded() -> None:
    dialogue = tracker()
    for index in range(30):
        dialogue.reference(tx(f"tx-{index}", "x" * 500))

    assert len(dialogue.state.last_referenced) == MAX_REFERENCES
    assert all(len(e.label) <= MAX_LABEL for e in dialogue.state.last_referenced)


def test_unknown_phrases_are_not_references() -> None:
    dialogue = tracker()
    dialogue.reference(tx("tx-1"))

    assert dialogue.resolve_reference("the blue one").status == "unresolved"
    assert dialogue.resolve_reference("").status == "unresolved"


# ------------------------------------------------------------------- clarification


def _ask(dialogue: DialogueTracker) -> None:
    dialogue.ask("which-account", [Option("acct-1", "Checking"), Option("acct-2", "Card")])


def test_an_answer_to_a_pending_question_picks_from_its_options() -> None:
    dialogue = tracker()
    _ask(dialogue)

    assert dialogue.resolve_reference("the first one").entity.id == "acct-1"  # type: ignore[union-attr]
    assert dialogue.resolve_reference("the second one").entity.id == "acct-2"  # type: ignore[union-attr]
    assert dialogue.resolve_reference("card").entity.id == "acct-2"  # type: ignore[union-attr]
    assert dialogue.resolve_reference("the third one").status == "unresolved"


def test_that_one_among_several_options_is_ambiguous_not_guessed() -> None:
    dialogue = tracker()
    _ask(dialogue)

    reference = dialogue.resolve_reference("that one")

    assert reference.status == "ambiguous" and len(reference.candidates) == 2


def test_a_clarification_expires() -> None:
    clock = Clock()
    dialogue = tracker(clock=clock)
    dialogue.reference(tx("tx-1"))
    _ask(dialogue)
    clock.advance(minutes=3)

    reference = dialogue.resolve_reference("the first one")

    assert reference.status == "unresolved"
    assert dialogue.resolve_reference("it").entity.id == "tx-1"  # type: ignore[union-attr]


def test_a_barge_in_cancels_the_clarification_and_bumps_the_epoch() -> None:
    store = MemoryDialogueStore()
    dialogue = tracker(store)
    _ask(dialogue)

    dialogue.barge_in(4)

    assert dialogue.state.pending_clarification is None and dialogue.state.turn_epoch == 4
    assert tracker(store).state.pending_clarification is None


# --------------------------------------------------------------- undo and persistence


def test_an_accepted_proposal_sets_the_undo_pointer_and_clears_the_working_intent() -> None:
    dialogue = tracker()
    dialogue.begin_intent("finance.add_expense", {"amount": "12.00"}, ["category"])
    dialogue.accept_proposal("act-1", [tx("tx-1", "Lunch")])

    assert dialogue.undo_target() == "act-1"
    assert dialogue.state.active_intent is None and dialogue.state.missing_slots == []
    assert dialogue.resolve_reference("it").entity.id == "tx-1"  # type: ignore[union-attr]


def test_undo_walks_back_one_action_at_a_time() -> None:
    dialogue = tracker()
    for index in (1, 2, 3):
        dialogue.accept_proposal(f"act-{index}")

    assert dialogue.undo_target() == "act-3"
    dialogue.undone()
    assert dialogue.undo_target() == "act-2"
    dialogue.undone()
    dialogue.undone()
    assert dialogue.undo_target() is None
    dialogue.undone()  # nothing left: harmless


def test_state_is_saved_after_each_accepted_proposal_and_resumes_after_a_restart() -> None:
    store = MemoryDialogueStore()
    clock = Clock()
    first = tracker(store, clock)
    first.accept_proposal("act-1", [tx("tx-1", "Lunch")])
    first.accept_proposal("act-2", [tx("tx-2", "Coffee")])

    clock.advance(minutes=5)
    after_restart = tracker(store, clock)  # a new process, a new session, the same device

    assert after_restart.undo_target() == "act-2"
    assert after_restart.resolve_reference("it").entity.id == "tx-2"  # type: ignore[union-attr]
    assert after_restart.resolve_reference("the one before").entity.id == "tx-1"  # type: ignore[union-attr]


def test_a_different_device_does_not_see_the_state() -> None:
    store = MemoryDialogueStore()
    tracker(store, device="device-0001").accept_proposal("act-1", [tx("tx-1")])

    other = tracker(store, device="device-0002")

    assert other.undo_target() is None and other.resolve_reference("it").status == "unresolved"


def test_old_references_and_questions_are_dropped_on_resume_but_a_recent_undo_stays() -> None:
    store = MemoryDialogueStore()
    clock = Clock()
    first = tracker(store, clock)
    first.accept_proposal("act-1", [tx("tx-1")])

    clock.advance(minutes=45)
    later = tracker(store, clock)

    assert later.resolve_reference("it").status == "unresolved", "45 minutes later 'it' is stale"
    assert later.undo_target() == "act-1", "undo is still offered inside 24 hours"


def test_an_undo_older_than_a_day_is_not_offered() -> None:
    store = MemoryDialogueStore()
    clock = Clock()
    tracker(store, clock).accept_proposal("act-1")

    clock.advance(hours=25)

    assert tracker(store, clock).undo_target() is None


# ------------------------------------------------------------------------- the file store


def test_the_file_store_round_trips_a_state(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")
    clock = Clock()
    tracker(store, clock).accept_proposal("act-1", [tx("tx-1", "Lunch")])

    resumed = tracker(store, clock)

    assert resumed.undo_target() == "act-1"
    assert resumed.resolve_reference("it").entity == tx("tx-1", "Lunch")  # type: ignore[union-attr]


def test_a_device_id_cannot_name_a_path(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")

    tracker(store, device="../../escape\\..\\x").accept_proposal("act-1")

    written = list((tmp_path / "dialogue").glob("*.json"))
    assert len(written) == 1 and written[0].parent == tmp_path / "dialogue"
    assert not (tmp_path / "escape").exists()
    assert len(written[0].stem) == 32 and written[0].stem.isalnum()


def test_a_corrupt_file_starts_fresh_instead_of_failing(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")
    tracker(store).accept_proposal("act-1")
    (path,) = list((tmp_path / "dialogue").glob("*.json"))
    path.write_text("{not json", encoding="utf-8")

    assert tracker(store).undo_target() is None


def test_a_file_that_is_not_dialogue_state_is_ignored(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")
    tracker(store).accept_proposal("act-1")
    (path,) = list((tmp_path / "dialogue").glob("*.json"))

    for junk in ("[]", '"text"', "123", '{"committed": [{"nope": 1}]}'):
        path.write_text(junk, encoding="utf-8")
        assert tracker(store).undo_target() is None, junk


def test_an_oversized_file_is_ignored(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")
    tracker(store).accept_proposal("act-1")
    (path,) = list((tmp_path / "dialogue").glob("*.json"))
    path.write_text(json.dumps({"filler": "x" * (MAX_FILE_BYTES + 10)}), encoding="utf-8")

    assert tracker(store).undo_target() is None


def test_saving_to_an_unwritable_place_does_not_stop_the_conversation(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    dialogue = tracker(FileDialogueStore(blocker / "dialogue"))

    dialogue.accept_proposal("act-1", [tx("tx-1")])

    assert dialogue.undo_target() == "act-1", "still works in memory for this run"


def test_no_temp_files_are_left_behind(tmp_path: Path) -> None:
    store = FileDialogueStore(tmp_path / "dialogue")
    dialogue = tracker(store)
    for index in range(5):
        dialogue.accept_proposal(f"act-{index}")

    assert [p.suffix for p in (tmp_path / "dialogue").iterdir()] == [".json"]
