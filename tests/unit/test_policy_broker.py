"""B3a: signed grants, broker, ledger, false success (AR-WIN-008/009, AR-AGT-004/5/6/14/16/18)."""

from __future__ import annotations

import base64
import json
import random
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language import outcomes
from reva_core.policy.authorize import Proposal, args_hash
from reva_core.policy.broker import (
    MAX_OPEN,
    Broker,
    BrokerFull,
    GrantMismatch,
    UnknownAction,
)
from reva_core.policy.grants import (
    Grant,
    GrantSigner,
    GrantVerifier,
    ReplayCache,
    load_or_create_signer,
)
from reva_core.policy.ledger import MemoryLedger, SqliteLedger, redact_args
from reva_core.policy.registry import DEFAULT_REGISTRY
from reva_core.storage.migrations import MIGRATIONS

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def make(ledger=None, clock: Clock | None = None):
    clock = clock or Clock()
    signer = load_or_create_signer(InMemoryKeyProvider())
    broker = Broker(signer=signer, ledger=ledger or MemoryLedger(), clock=clock)
    verifier = GrantVerifier(signer.public_key_pem(), ReplayCache())
    return broker, verifier, signer, clock


_ids = iter(range(1, 10**9))


def proposal(capability="windows.app.open", args=None, **kwargs) -> Proposal:
    args = {"app_key": "notepad"} if args is None else args
    return Proposal(proposal_id=f"act-{next(_ids):08d}", capability=capability, args=args, **kwargs)


def verify(verifier: GrantVerifier, order, clock: Clock, **overrides):
    args = dict(
        now=clock.now,
        capability=order.capability,
        args_hash=args_hash(order.args),
        target_device=order.target_device,
        actor="owner",
    )
    args.update(overrides)
    return verifier.verify(order.grant, order.signature, **args)


GOOD_EVIDENCE = {
    "windows.app.open": {"kind": "process_started", "ref": "pid:4242 window:0x1"},
    "windows.app.close": {"kind": "process_exited", "ref": "pid:4242"},
    "finance.add_transaction": {"kind": "kernel_event", "ref": "evt-12345678"},
}

# --------------------------------------------------------------------------- grants


def test_a_signed_grant_verifies_and_is_bound_to_this_action() -> None:
    broker, verifier, _, clock = make()

    view = broker.propose(proposal())

    assert view.status == "granted" and view.order is not None
    assert len(base64.urlsafe_b64decode(view.order.signature + "==")) == 64  # raw r||s
    assert verify(verifier, view.order, clock).ok


def test_a_changed_grant_field_breaks_the_signature() -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None

    for field, value in (
        ("capability", "windows.app.close"),
        ("args_hash", "0" * 64),
        ("target_device", "other"),
        ("actor", "intruder"),
        ("expires_at", (clock.now + timedelta(days=9)).isoformat()),
        ("idempotency_key", "fresh-key"),
        ("action_id", "act-hijack"),
    ):
        forged = replace(order.grant, **{field: value})
        result = verifier.verify(
            forged, order.signature, now=clock.now, capability=forged.capability,
            args_hash=forged.args_hash, target_device=forged.target_device, actor=forged.actor,
        )  # fmt: skip
        assert result.reason == "BAD_SIGNATURE", field


def test_a_grant_signed_by_another_key_is_refused() -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None
    stranger = GrantSigner(ec.generate_private_key(ec.SECP256R1()))

    assert verifier.verify(
        order.grant, stranger.sign(order.grant), now=clock.now, capability=order.capability,
        args_hash=args_hash(order.args), target_device=order.target_device, actor="owner",
    ).reason == "BAD_SIGNATURE"  # fmt: skip


def test_a_replayed_grant_does_nothing_the_second_time() -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None

    first = verify(verifier, order, clock)
    second = verify(verifier, order, clock)

    assert first.ok and second.reason == "REPLAYED"


def test_substituted_capability_args_target_or_actor_are_refused() -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None

    assert (
        verify(verifier, order, clock, capability="windows.app.close").reason
        == "CAPABILITY_MISMATCH"
    )
    assert (
        verify(verifier, order, clock, args_hash=args_hash({"app_key": "chrome"})).reason
        == "ARGS_MISMATCH"
    )
    assert verify(verifier, order, clock, target_device="phone-1").reason == "WRONG_TARGET"
    assert verify(verifier, order, clock, actor="someone").reason == "WRONG_ACTOR"
    assert verify(verifier, order, clock).ok  # none of the failed attempts used up the key


def test_a_grant_expires_after_a_minute_and_is_not_valid_from_the_future() -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None

    assert verify(verifier, order, clock, now=clock.now + timedelta(seconds=61)).reason == "EXPIRED"
    assert (
        verify(verifier, order, clock, now=clock.now - timedelta(seconds=30)).reason
        == "NOT_YET_VALID"
    )
    assert verify(verifier, order, clock, now=clock.now + timedelta(seconds=59)).ok


@pytest.mark.parametrize("signature", ["", "not base64!", "AAAA", "A" * 200, "_" * 86])
def test_a_malformed_signature_is_refused_without_raising(signature: str) -> None:
    broker, verifier, _, clock = make()
    order = broker.propose(proposal()).order
    assert order is not None

    result = verifier.verify(
        order.grant, signature, now=clock.now, capability=order.capability,
        args_hash=args_hash(order.args), target_device=order.target_device, actor="owner",
    )  # fmt: skip

    assert not result.ok and result.reason in ("MALFORMED", "BAD_SIGNATURE")


def test_the_grant_key_is_stable_across_restarts_and_never_recreated() -> None:
    provider = InMemoryKeyProvider()
    first = load_or_create_signer(provider)
    second = load_or_create_signer(provider)

    assert first.public_key_pem() == second.public_key_pem()


def test_the_public_key_file_holds_no_secret(tmp_path: Path) -> None:
    signer = load_or_create_signer(InMemoryKeyProvider())

    path = signer.write_public_key(tmp_path)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("-----BEGIN PUBLIC KEY-----") and "PRIVATE" not in text


def test_a_grant_round_trips_through_a_dict_and_rejects_extra_or_missing_fields() -> None:
    broker, _, _, _ = make()
    grant = broker.propose(proposal()).order.grant  # type: ignore[union-attr]

    assert Grant.from_dict(grant.to_dict()) == grant
    with pytest.raises(ValueError):
        Grant.from_dict({**grant.to_dict(), "extra": "x"})
    with pytest.raises(ValueError):
        Grant.from_dict({k: v for k, v in grant.to_dict().items() if k != "actor"})


# ---------------------------------------------------------------------------- broker


def test_a_t1_open_is_granted_at_once_and_nothing_is_claimed_yet() -> None:
    broker, _, _, _ = make()

    view = broker.propose(proposal())

    assert (view.status, view.tier, view.speak) == ("granted", "T1", None)


def test_t0_is_allowed_with_no_grant_because_core_answers_it_itself() -> None:
    broker, _, _, _ = make()

    view = broker.propose(proposal("finance.summary", {"period": "month"}))

    assert view.status == "allowed" and view.order is None and view.speak is None


def test_verified_with_evidence_is_the_only_way_to_hear_opened() -> None:
    broker, _, _, _ = make()
    view = broker.propose(proposal())
    assert view.order is not None

    done = broker.report(
        view.action_id, view.order.grant.grant_id, "verified", GOOD_EVIDENCE["windows.app.open"]
    )

    assert done.status == "verified" and done.speak == "Opened Notepad."


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        {"kind": "process_started"},
        {"kind": "process_started", "ref": ""},
        {"kind": "kernel_event", "ref": "evt-1"},  # the wrong kind for an app open
        {"kind": "process_started", "ref": "x" * 500},
        {"kind": "process_started", "ref": 12345},
        "the app opened successfully",  # model-style narration is not evidence
        ["process_started"],
    ],
)
def test_verified_without_proper_evidence_is_recorded_as_unknown(evidence) -> None:
    broker, _, _, _ = make()
    view = broker.propose(proposal())
    assert view.order is not None

    done = broker.report(view.action_id, view.order.grant.grant_id, "verified", evidence)

    assert done.status == "unknown" and done.speak == outcomes.UNKNOWN
    assert "opened" not in (done.speak or "").lower()


def test_failed_and_denied_never_sound_like_success() -> None:
    for status, text in (
        ("failed", outcomes.FAILED),
        ("denied", outcomes.DENIED),
        ("unknown", outcomes.UNKNOWN),
    ):
        broker, _, _, _ = make()
        view = broker.propose(proposal())
        assert view.order is not None
        assert broker.report(view.action_id, view.order.grant.grant_id, status, None).speak == text


def test_in_progress_statuses_claim_nothing_and_the_first_final_answer_stands() -> None:
    broker, _, _, _ = make()
    view = broker.propose(proposal())
    assert view.order is not None
    grant_id = view.order.grant.grant_id

    assert broker.report(view.action_id, grant_id, "attempted").speak == outcomes.IN_PROGRESS
    assert broker.report(view.action_id, grant_id, "observed").speak == outcomes.IN_PROGRESS
    assert (
        broker.report(view.action_id, grant_id, "attempted").status == "observed"
    )  # no going back
    final = broker.report(view.action_id, grant_id, "failed", None)
    late = broker.report(view.action_id, grant_id, "verified", GOOD_EVIDENCE["windows.app.open"])

    assert final.status == "failed" and late.status == "failed" and late.speak == outcomes.FAILED


def test_an_outcome_with_the_wrong_grant_is_refused_and_changes_nothing() -> None:
    broker, _, _, _ = make()
    first = broker.propose(proposal())
    second = broker.propose(proposal())
    assert first.order is not None and second.order is not None

    with pytest.raises(GrantMismatch):
        broker.report(
            first.action_id,
            second.order.grant.grant_id,
            "verified",
            GOOD_EVIDENCE["windows.app.open"],
        )
    with pytest.raises(GrantMismatch):
        broker.report(first.action_id, "made-up", "verified", GOOD_EVIDENCE["windows.app.open"])

    assert broker.get(first.action_id).status == "granted"


def test_an_outcome_for_an_action_that_was_never_granted_is_refused() -> None:
    broker, _, _, _ = make()
    asked = broker.propose(proposal("windows.app.close", {"app_key": "notepad"}))

    with pytest.raises(GrantMismatch):
        broker.report(asked.action_id, "anything", "verified", GOOD_EVIDENCE["windows.app.close"])
    with pytest.raises(UnknownAction):
        broker.report("act-nonexistent", "x", "verified", None)
    granted = broker.propose(proposal())
    assert granted.order is not None
    with pytest.raises(ValueError):
        broker.report(granted.action_id, granted.order.grant.grant_id, "bogus", None)


# ------------------------------------------------------------------ T2 approval flow


def close_proposal() -> Proposal:
    return proposal("windows.app.close", {"app_key": "notepad"})


def test_t2_waits_for_approval_and_says_so() -> None:
    broker, _, _, clock = make()

    view = broker.propose(close_proposal())

    assert (view.status, view.reason, view.speak) == (
        "awaiting_approval",
        "APPROVAL_REQUIRED",
        outcomes.NOT_APPROVED,
    )
    assert view.order is None and view.deadline is not None


def test_a_spoken_yes_never_approves() -> None:
    broker, _, _, _ = make()
    view = broker.propose(close_proposal())

    for via in ("speech", "voice", "api", ""):
        attempt = broker.approve(view.action_id, via=via, device="local")
        assert attempt.status == "awaiting_approval" and attempt.order is None, via


def test_a_click_on_the_wrong_screen_never_approves() -> None:
    broker, _, _, _ = make()
    view = broker.propose(replace(close_proposal(), target_device="pc-0001"))

    assert (
        broker.approve(view.action_id, via="tap", device="phone-0001").status == "awaiting_approval"
    )
    approved = broker.approve(view.action_id, via="click", device="pc-0001")
    assert approved.status == "granted" and approved.order is not None


def test_a_click_issues_the_grant_and_a_second_approval_changes_nothing() -> None:
    broker, verifier, _, clock = make()
    view = broker.propose(close_proposal())

    approved = broker.approve(view.action_id, via="click", device="local")
    again = broker.approve(view.action_id, via="click", device="local")

    assert approved.status == "granted" and approved.order is not None
    assert again.status == "granted" and again.order is not None
    assert again.order.grant.grant_id == approved.order.grant.grant_id
    assert verify(verifier, approved.order, clock).ok


def test_an_approval_that_comes_too_late_expires_the_request() -> None:
    broker, _, _, clock = make()
    view = broker.propose(close_proposal())

    clock.advance(minutes=2, seconds=1)
    late = broker.approve(view.action_id, via="click", device="local")

    assert late.status == "expired" and late.speak == outcomes.EXPIRED and late.order is None
    assert broker.get(view.action_id).status == "expired"


def test_the_user_can_say_no_with_a_click() -> None:
    broker, _, _, _ = make()
    view = broker.propose(close_proposal())

    denied = broker.deny(view.action_id)

    assert denied.status == "denied" and denied.speak == outcomes.DENIED
    assert broker.approve(view.action_id, via="click", device="local").status == "denied"


def test_t2_arguments_cannot_be_swapped_after_the_request_was_made() -> None:
    broker, _, _, _ = make()
    view = broker.propose(close_proposal())
    swapped = replace(close_proposal(), proposal_id=view.action_id, args={"app_key": "chrome"})

    again = broker.propose(swapped)  # same id, different request

    assert again.status == "refused" and again.reason == "STATE_MISMATCH"
    approved = broker.approve(view.action_id, via="click", device="local")
    assert approved.order is not None and approved.order.args == {"app_key": "notepad"}


def test_the_same_proposal_twice_is_one_action() -> None:
    broker, _, _, _ = make()
    p = proposal()

    first = broker.propose(p)
    second = broker.propose(p)

    assert first.order is not None and second.order is not None
    assert first.order.grant.grant_id == second.order.grant.grant_id


# ---------------------------------------------------------------- refusals and limits


@pytest.mark.parametrize(
    "name",
    [
        "finance.transfer",
        "finance.pay",
        "finance.purchase",
        "shell.run",
        "files.delete",
        "email.send",
        "health.dose",
    ],
)
def test_forbidden_capabilities_get_the_refusal_template_and_never_a_grant(name: str) -> None:
    broker, _, _, _ = make()

    view = broker.propose(proposal(name, {"amount": 500}))

    assert view.status == "refused" and view.reason == "FORBIDDEN_CAPABILITY" and view.order is None
    expected = {"finance": outcomes.REFUSED_MONEY, "health": outcomes.REFUSED_MEDICAL}.get(
        name.split(".")[0], outcomes.REFUSED_GENERIC
    )
    assert view.speak == expected


def test_a_hosted_model_proposal_without_consent_is_refused() -> None:
    broker, _, _, _ = make()

    view = broker.propose(proposal("finance.summary", {"period": "month"}, hosted_origin=True))

    assert view.status == "refused" and view.reason == "CONSENT_REQUIRED"


def test_too_many_waiting_actions_is_a_clean_limit() -> None:
    broker, _, _, _ = make()
    for _ in range(MAX_OPEN):
        broker.propose(close_proposal())

    with pytest.raises(BrokerFull):
        broker.propose(close_proposal())


# ------------------------------------------------------------------------ the ledger


def test_every_step_is_recorded_in_order_with_redacted_arguments() -> None:
    ledger = MemoryLedger()
    broker, _, _, _ = make(ledger)
    view = broker.propose(
        proposal(
            "finance.add_transaction",
            {"amount": 1234.5, "currency": "USD", "category": "therapy", "note": "private note"},
        )
    )
    approved = broker.approve(view.action_id, via="tap", device="local")
    assert approved.order is not None
    broker.report(
        view.action_id,
        approved.order.grant.grant_id,
        "verified",
        GOOD_EVIDENCE["finance.add_transaction"],
    )

    rows = ledger.rows(view.action_id)

    assert [r.kind for r in rows] == [
        "proposed",
        "awaiting_approval",
        "approved",
        "granted",
        "outcome",
    ]
    assert [r.seq for r in rows] == [0, 1, 2, 3, 4]
    text = json.dumps([r.payload for r in rows])
    for secret in ("1234.5", "therapy", "private note"):
        assert secret not in text
    assert rows[0].payload["args"]["amount"] == "<redacted>"
    assert rows[-1].payload["status"] == "verified"


def test_only_enum_valued_arguments_stay_readable() -> None:
    cap = DEFAULT_REGISTRY.get("windows.app.open")
    assert cap is not None
    assert redact_args(cap, {"app_key": "notepad"}) == {"app_key": "notepad"}
    assert redact_args(cap, {"app_key": "not in the list", "x": 1}) == {
        "app_key": "<redacted>",
        "x": "<redacted>",
    }


def _sqlite_ledger() -> tuple[SqliteLedger, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    for migration in MIGRATIONS:
        conn.executescript(migration.sql)
    return SqliteLedger(conn), conn


def test_the_sqlite_ledger_stores_rows_and_refuses_changes_and_deletes() -> None:
    ledger, conn = _sqlite_ledger()
    broker, _, _, _ = make(ledger)
    view = broker.propose(proposal())

    rows = ledger.rows(view.action_id)
    assert [r.kind for r in rows] == ["proposed", "granted"]
    assert ledger.recent(5)[0].kind == "granted"
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE action_events SET kind = 'outcome'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM action_events")
    assert len(ledger.rows(view.action_id)) == 2


# ------------------------------------------------- false success: 0 of 100 (and more)


def _scenario(rng: random.Random) -> dict:
    return {
        "capability": rng.choice(list(GOOD_EVIDENCE)),
        "approve": rng.choice(["click", "speech", "wrong_device", "none", "late"]),
        "report": rng.choice(
            [
                "verified", "verified_no_evidence", "verified_wrong_kind", "failed", "unknown",
                "denied", "attempted", "none", "wrong_grant",
            ]
        ),  # fmt: skip
        "late_report": rng.choice([None, "verified", "failed"]),
        "tamper_args": rng.random() < 0.2,
    }  # fmt: skip


ARGS = {
    "windows.app.open": {"app_key": "notepad"},
    "windows.app.close": {"app_key": "spotify"},
    "finance.add_transaction": {
        "amount": 12,
        "currency": "USD",
        "category": "food",
        "note": "lunch",
    },
}


def _run(rng: random.Random) -> tuple[bool, str]:
    s = _scenario(rng)
    clock = Clock()
    broker, _, _, _ = make(clock=clock)
    p = proposal(s["capability"], dict(ARGS[s["capability"]]), target_device="pc-1")
    view = broker.propose(p)
    spoken = [view.speak or ""]
    if view.status == "awaiting_approval":
        if s["approve"] == "late":
            clock.advance(minutes=3)
        device = "other" if s["approve"] == "wrong_device" else "pc-1"
        via = "speech" if s["approve"] == "speech" else "click"
        if s["approve"] != "none":
            view = broker.approve(view.action_id, via=via, device=device)
            spoken.append(view.speak or "")
    if view.order is not None and s["report"] != "none":
        capability = s["capability"]
        evidence = {
            "verified": GOOD_EVIDENCE[capability],
            "verified_no_evidence": None,
            "verified_wrong_kind": {"kind": "none", "ref": "x"},
        }.get(s["report"], GOOD_EVIDENCE[capability])
        status = "verified" if s["report"].startswith("verified") else s["report"]
        grant_id = "forged" if s["report"] == "wrong_grant" else view.order.grant.grant_id
        try:
            done = broker.report(view.action_id, grant_id, status, evidence)
        except GrantMismatch:
            done = broker.get(view.action_id)
        spoken.append(done.speak or "")
        if s["late_report"]:
            late = broker.report(
                view.action_id,
                view.order.grant.grant_id,
                s["late_report"],
                GOOD_EVIDENCE[capability],
            )
            spoken.append(late.speak or "")
    text = " ".join(spoken).lower()
    claims = any(word in text for word in outcomes.SUCCESS_WORDS)
    final = broker.get(view.action_id)
    honest = final.status == "verified" and any(
        r.kind == "outcome"
        and r.payload.get("status") == "verified"
        and r.payload.get("evidence", {}).get("kind") == final.evidence_kind
        for r in broker.ledger.rows(view.action_id)
    )
    # A success sentence is allowed only when the final status is verified with evidence on file.
    return claims and not honest, text


def test_a_success_sentence_is_never_produced_without_a_verified_outcome_with_evidence() -> None:
    rng = random.Random(42)  # noqa: S311 - test data, not security
    violations = [text for ok, text in (_run(rng) for _ in range(500)) if ok]

    assert violations == []  # false-success corpus: 0 of 500 (the bar is 0 of 100)


def test_every_success_phrase_comes_from_a_template_for_a_verified_status_only() -> None:
    for status in ("attempted", "observed", "failed", "unknown", "denied"):
        for capability, args in ARGS.items():
            text = outcomes.outcome_text(status, capability, args).lower()
            assert not any(w in text for w in ("opened", "saved", "closed", "added")), (
                status,
                text,
            )
    assert (
        outcomes.outcome_text("verified", "windows.app.close", {"app_key": "spotify"})
        == "Closed Spotify."
    )
    assert (
        outcomes.outcome_text(
            "verified", "finance.add_transaction", ARGS["finance.add_transaction"]
        )
        == "Saved."
    )


# ----------------------------------------------------------- registry absence (AR-AGT-018)


def test_no_registry_names_a_payment_transfer_purchase_bank_login_or_dosing_capability() -> None:
    words = (
        "pay",
        "transfer",
        "purchase",
        "buy",
        "bank",
        "dose",
        "dosing",
        "diagnos",
        "shell",
        "delete",
        "email.send",
        "install",
        "wire",
    )
    for path in (
        ROOT / "contracts" / "capability-registry.v2.json",
        ROOT / "reva_core" / "policy" / "data" / "capability-registry.v2.json",
    ):
        document = json.loads(path.read_text("utf-8"))
        for entry in document["capabilities"]:
            name = entry["capability"].lower()
            assert not any(w in name for w in words), (path.name, name)
        # the document itself must keep naming what is forbidden
        assert {
            "finance.pay",
            "finance.transfer",
            "finance.purchase",
            "finance.bank_login",
            "health.dose",
            "shell.",
            "files.delete",
            "email.send",
        } <= set(document["forbidden_capability_prefixes"])
