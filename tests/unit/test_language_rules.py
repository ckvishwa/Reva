"""B3b: rule fast path, entity ladder, refusals and the router wired to the broker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language import outcomes
from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.entities import AppResolver
from reva_core.language.router import IntentRouter
from reva_core.language.rules import parse
from reva_core.policy.authorize import Resolution
from reva_core.policy.broker import Broker
from reva_core.policy.grants import load_or_create_signer
from reva_core.policy.ledger import MemoryLedger

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
KEYS = ("notepad", "calculator", "chrome", "vscode", "spotify")
RESOLVER = AppResolver(KEYS)


def rig() -> tuple[IntentRouter, Broker]:
    broker = Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
    )
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    return IntentRouter(dialogue, broker), broker


# ------------------------------------------------------------------------- ladder


@pytest.mark.parametrize(
    ("phrase", "key", "resolution"),
    [
        ("notepad", "notepad", Resolution.EXACT),
        ("the Notepad app", "notepad", Resolution.EXACT),
        ("vs code", "vscode", Resolution.ALIAS),
        ("visual studio code", "vscode", Resolution.ALIAS),
        ("google chrome", "chrome", Resolution.ALIAS),
        ("calc", "calculator", Resolution.ALIAS),
        ("note pad", "notepad", Resolution.LEXICAL),
        ("spotfy", "spotify", Resolution.FUZZY),
        ("calculater", "calculator", Resolution.FUZZY),
    ],
)
def test_ladder_rungs(phrase: str, key: str, resolution: Resolution) -> None:
    match = RESOLVER.resolve(phrase)

    assert match.key == key and match.entity.resolution == resolution


@pytest.mark.parametrize("phrase", ["photoshop", "word", "", "the", "xyzzy", "zoom"])
def test_unknown_names_do_not_resolve(phrase: str) -> None:
    assert RESOLVER.resolve(phrase).key is None


def test_leftover_content_words_are_reported_not_dropped() -> None:
    match = RESOLVER.resolve("notepad tomorrow morning")

    assert match.key == "notepad" and match.leftover == ("tomorrow", "morning")
    assert RESOLVER.resolve("the notepad please").leftover == ()


def test_fuzzy_reports_a_margin_and_a_vector_shadow_never_changes_the_answer() -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def shadow(phrase: str, keys: tuple[str, ...]) -> object:
        seen.append((phrase, keys))
        return {"chrome": 0.99}

    def broken(phrase: str, keys: tuple[str, ...]) -> object:
        raise RuntimeError("embedding down")

    plain = RESOLVER.resolve("spotfy")
    shadowed = AppResolver(KEYS, shadow=shadow).resolve("spotfy")
    survived = AppResolver(KEYS, shadow=broken).resolve("spotfy")

    assert plain == shadowed == survived and plain.entity.margin is not None
    assert seen == [("spotfy", KEYS)]


# -------------------------------------------------------------------------- rules


@pytest.mark.parametrize(
    ("text", "capability", "args"),
    [
        ("open notepad", "windows.app.open", {"app_key": "notepad"}),
        ("Open VS Code.", "windows.app.open", {"app_key": "vscode"}),
        ("please launch the calculator", "windows.app.open", {"app_key": "calculator"}),
        ("close spotify", "windows.app.close", {"app_key": "spotify"}),
        ("quit chrome", "windows.app.close", {"app_key": "chrome"}),
        ("what's on today", "today.get", {}),
        ("how much did I spend this week", "finance.summary", {"period": "week"}),
        ("how much did I spend", "finance.summary", {"period": "month"}),
        ("how did I sleep this week", "health.weekly", {}),
        ("show my health this week", "health.weekly", {}),
        ("show my spending for the year", "finance.summary", {"period": "year"}),
        ("remember that the wifi code is on the fridge", "memory.remember",
         {"content": "the wifi code is on the fridge"}),
        ("what did I say about the dentist", "memory.recall", {"query": "the dentist"}),
    ],
)  # fmt: skip
def test_positive_fixtures(text: str, capability: str, args: dict) -> None:
    hit = parse(text, RESOLVER)

    assert hit is not None and hit.capability == capability and hit.args == args


@pytest.mark.parametrize(
    "text",
    [
        "", "hello", "tell me a joke", "what time is it", "open", "the notepad is open",
        "I opened a bug", "closing thoughts", "remember", "add twelve dollars for lunch",
        "what is the order of operations", "I need to buy time", "start the day well",
    ],
)  # fmt: skip
def test_negative_fixtures_fall_through_to_the_assistant(text: str) -> None:
    hit = parse(text, RESOLVER)

    # A few of these are refused on purpose (buy); the rest must produce nothing.
    if text == "I need to buy time":
        assert hit is not None and hit.capability == "finance.purchase"
    elif text == "start the day well":
        assert hit is not None and hit.unknown_app == "the day well"
    elif text == "open":
        assert hit is None
    else:
        assert hit is None, (text, hit)


@pytest.mark.parametrize(
    ("text", "capability"),
    [
        ("pay my rent", "finance.transfer"),
        ("send 500 dollars to John", "finance.transfer"),
        ("transfer money to savings", "finance.transfer"),
        ("buy a laptop", "finance.purchase"),
        ("order me a pizza", "finance.purchase"),
        ("log into my bank", "finance.bank_login"),
        ("what dose of ibuprofen should I take", "health.dose"),
        ("diagnose my cough", "health.dose"),
        ("run a command in powershell", "shell.run"),
        ("open the terminal and type rm", "shell.run"),
        ("delete all my files", "files.delete"),
        ("erase the photos folder", "files.delete"),
        ("send an email to my boss", "email.send"),
        ("email my landlord to say hi", "email.send"),
    ],
)
def test_forbidden_requests_are_recognised_before_anything_else(text: str, capability: str) -> None:
    hit = parse(text, RESOLVER)

    assert hit is not None and hit.capability == capability


# -------------------------------------------------- router + broker (the whole path)


def test_open_notepad_is_granted_and_says_it_asked_not_that_it_opened() -> None:
    router, broker = rig()

    turn = router.route("open notepad", now=NOW)

    assert turn.kind == "action" and turn.action is not None and turn.action.status == "granted"
    assert turn.reply == "Asking your PC to open Notepad."
    assert "opened" not in turn.reply.lower()


def test_close_waits_for_a_click_and_a_spoken_yes_does_not_approve() -> None:
    router, broker = rig()

    asked = router.route("close spotify", now=NOW)
    yes = router.route("yes", now=NOW)

    assert asked.kind == "approval" and asked.reply == "Close Spotify? Approve it on screen."
    assert yes.kind == "chat"  # "yes" with nothing pending is just talk
    assert (
        asked.action is not None
        and broker.get(asked.action.action_id).status == "awaiting_approval"
    )


def test_a_fuzzy_name_is_asked_about_and_only_a_yes_proposes_it() -> None:
    router, broker = rig()

    ask = router.route("open spotfy", now=NOW)
    assert ask.kind == "clarify" and ask.reply == "Did you mean Spotify?"
    assert broker.ledger.recent(10) == []  # nothing proposed yet

    done = router.route("yes", now=NOW)
    assert done.kind == "action" and done.action is not None
    assert done.action.order is not None and done.action.order.args == {"app_key": "spotify"}


def test_a_guess_followed_by_something_else_is_dropped_and_no() -> None:
    router, broker = rig()
    router.route("open spotfy", now=NOW)
    assert router.route("no", now=NOW).kind == "dismissed"
    router.route("open spotfy", now=NOW)
    other = router.route("open notepad", now=NOW)

    assert other.kind == "action" and other.action is not None
    assert other.action.order is not None and other.action.order.args == {"app_key": "notepad"}


def test_an_app_that_is_not_allowed_is_not_proposed_at_all() -> None:
    router, broker = rig()

    turn = router.route("open photoshop", now=NOW)

    assert turn.kind == "refused" and turn.reply == outcomes.UNKNOWN_APP
    assert broker.ledger.recent(10) == []


def test_extra_words_after_the_app_name_block_the_action() -> None:
    router, broker = rig()

    turn = router.route("open notepad tomorrow", now=NOW)

    assert turn.kind == "refused" and turn.reply == outcomes.NOT_UNDERSTOOD
    assert turn.action is not None and turn.action.reason == "UNRESOLVED_TERMS"
    assert turn.action.order is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pay my rent", outcomes.REFUSED_MONEY),
        ("transfer money to savings", outcomes.REFUSED_MONEY),
        ("buy a laptop", outcomes.REFUSED_MONEY),
        ("what dose of ibuprofen should I take", outcomes.REFUSED_MEDICAL),
        ("run a command in powershell", outcomes.REFUSED_GENERIC),
        ("delete all my files", outcomes.REFUSED_GENERIC),
        ("send an email to my boss", outcomes.REFUSED_GENERIC),
    ],
)
def test_refusals_come_from_templates_and_never_produce_a_grant(text: str, expected: str) -> None:
    router, broker = rig()

    turn = router.route(text, now=NOW)

    assert turn.kind == "refused" and turn.reply == expected
    assert turn.action is not None and turn.action.reason == "FORBIDDEN_CAPABILITY"
    assert turn.action.order is None


def test_read_only_requests_are_authorized_and_logged_then_answered_by_the_assistant() -> None:
    router, broker = rig()

    turn = router.route("how much did I spend this week", now=NOW)

    assert turn.kind == "chat" and turn.action is not None and turn.action.status == "allowed"
    assert [r.kind for r in broker.ledger.recent(5)] == ["proposed"]


def test_remembering_a_note_needs_a_click_too() -> None:
    router, _ = rig()

    turn = router.route("remember that the code is 1234", now=NOW)

    assert turn.kind == "approval" and turn.reply == "Save that note? Approve it on screen."


def test_the_voice_expense_goes_to_the_broker_on_yes_and_waits_for_a_tap() -> None:
    router, broker = rig()
    drafted = router.route("add twelve dollars for lunch", now=NOW)
    accepted = router.route("yes", now=NOW)

    assert drafted.kind == "proposed"
    assert (
        accepted.kind == "approval"
        and accepted.reply == "Add $12.00 for Food · Dining? Confirm on screen."
    )
    assert accepted.action is not None and accepted.action.capability == "finance.add_transaction"
    assert accepted.action.status == "awaiting_approval" and accepted.action.order is None
    approved = broker.approve(accepted.action.action_id, via="tap", device="local")
    assert approved.order is not None and approved.order.args["amount"] == 12.0
    ledger_text = str([r.payload for r in broker.ledger.rows(accepted.action.action_id)])
    assert "12.0" not in ledger_text and "lunch" not in ledger_text


def test_without_a_broker_the_old_behaviour_holds() -> None:
    dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
    router = IntentRouter(dialogue)

    assert router.route("open notepad", now=NOW).kind == "chat"
    router.route("add twelve dollars for lunch", now=NOW)
    assert "Nothing is saved yet" in (router.route("yes", now=NOW).reply or "")


def test_no_reply_from_this_path_contains_a_success_word() -> None:
    router, _ = rig()
    for text in ("open notepad", "close chrome", "pay my rent", "open spotfy", "open photoshop",
                 "remember that x is y", "open notepad tomorrow", "delete my files"):  # fmt: skip
        reply = (router.route(text, now=NOW).reply or "").lower()
        assert not any(word in reply.split() for word in ("opened", "closed", "saved", "done")), (
            text
        )
