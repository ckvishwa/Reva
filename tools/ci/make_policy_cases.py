"""Write the fixtures that keep the Android policy code identical to the PC's.

  tests/fixtures/authorize-cases.json   proposals + state -> the Python `authorize()` decision, and
                                        argument sets -> the Python `args_hash`
  tests/fixtures/rules-cases.json       sentences -> the Python rule fast path result (or none)

The Python code (`reva_core/policy`, `reva_core/language/rules.py`) is the reference. The Kotlin
port replays these files in `AuthorizeParityTest` and `RulesTest`; a Python test regenerates them in
memory and fails when the committed copy is stale (for example after a registry change).

Usage: python tools/ci/make_policy_cases.py [--check]
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reva_core.language import outcomes  # noqa: E402
from reva_core.language.entities import AppResolver  # noqa: E402
from reva_core.language.rules import parse  # noqa: E402
from reva_core.policy import authorize as policy  # noqa: E402
from reva_core.policy.registry import DEFAULT_REGISTRY  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
RESOLVER = AppResolver(("notepad",))


def _sample(schema: dict[str, Any]) -> Any:
    """One valid value for a schema of the subset the registry uses."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        return {name: _sample(props[name]) for name in schema.get("required", [])}
    if kind == "string":
        pattern = schema.get("pattern")
        if pattern == "^[A-Z]{3}$":
            return "USD"
        if schema.get("format") == "date-time":
            return "2026-10-16T09:00:00Z"
        return "x" * max(1, schema.get("minLength", 1))
    if kind == "number":
        return max(1, schema.get("minimum", 0)) + 0.5
    if kind == "integer":
        return max(1, schema.get("minimum", 0))
    if kind == "boolean":
        return True
    return "x"


def _variants(args: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    out = [args]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    if required:
        out.append({k: v for k, v in args.items() if k != required[0]})
    out.append({**args, "surprise": 1})
    for name, sub in props.items():
        wrong: Any = 5 if sub.get("type") == "string" else "text"
        out.append({**args, name: wrong})
        if "maxLength" in sub:
            out.append({**args, name: "y" * (sub["maxLength"] + 1)})
        if "enum" in sub:
            out.append({**args, name: "not-in-the-list"})
    return out


ENTITY_SETS: list[list[policy.Entity]] = [
    [],
    [policy.Entity("app", "notepad", policy.Resolution.EXACT)],
    [policy.Entity("app", "vs code", policy.Resolution.ALIAS)],
    [policy.Entity("amount", "twelve", policy.Resolution.TYPED_VALUE)],
    [policy.Entity("app", "spotfy", policy.Resolution.FUZZY, 0.8, 0.05, ("spotify", "spotter"))],
    [policy.Entity("app", "note pad", policy.Resolution.LEXICAL)],
    [policy.Entity("app", "thing", policy.Resolution.NONE)],
    [
        policy.Entity(
            "contact",
            "sam",
            policy.Resolution.CONFIRMED,
            1.0,
            0.01,
            ("sam a", "sam b", "sam c", "sam d"),
        )
    ],
    [policy.Entity("contact", "sam", policy.Resolution.ALIAS, 1.0, 0.4, ("sam a", "sam b"))],
]


def _entity_json(e: policy.Entity) -> dict[str, Any]:
    return {
        "slot": e.slot,
        "phrase": e.phrase,
        "resolution": e.resolution.value,
        "score": e.score,
        "margin": e.margin,
        "candidates": list(e.candidates),
    }


def _decision_json(d: policy.AuthorizationDecision) -> dict[str, Any]:
    return {
        "allowed": d.allowed,
        "reason": d.reason,
        "tier": d.tier,
        "unresolved": list(d.unresolved),
        "clarification": d.clarification,
        "problems": list(d.problems),
    }


def _run(
    capability: str,
    args: dict[str, Any],
    entities: list[policy.Entity],
    unresolved: tuple[str, ...],
    approval_spec: dict[str, Any] | None,
    consent: dict[str, bool],
    scopes: list[str] | None,
    hosted: bool,
    target_device: str,
    case_id: str,
) -> dict[str, Any]:
    proposal = policy.Proposal(
        proposal_id="prop-0001",
        capability=capability,
        args=args,
        entities=tuple(entities),
        unresolved_terms=unresolved,
        source="rule",
        origin_device="phone-1",
        target_device=target_device,
        hosted_origin=hosted,
    )
    approval = None
    approval_json = None
    if approval_spec is not None:
        approval = policy.Approval(
            proposal_id=approval_spec["proposal_id"],
            args_hash=approval_spec["args_hash"] or policy.args_hash(args),
            target_device=approval_spec["target_device"],
            user=approval_spec["user"],
            via=approval_spec["via"],
            expires_at=NOW + timedelta(seconds=approval_spec["expires_in_s"]),
        )
        approval_json = {**approval_spec, "args_hash": approval.args_hash}
    state = policy.AuthState(
        now=NOW,
        approval=approval,
        user="owner",
        consent=consent,
        device_scopes=frozenset(scopes) if scopes is not None else None,
    )
    decision = policy.authorize(proposal, state, DEFAULT_REGISTRY)
    return {
        "id": case_id,
        "proposal": {
            "proposal_id": proposal.proposal_id,
            "capability": capability,
            "args": args,
            "entities": [_entity_json(e) for e in entities],
            "unresolved_terms": list(unresolved),
            "origin_device": proposal.origin_device,
            "target_device": target_device,
            "hosted_origin": hosted,
        },
        "state": {"approval": approval_json, "consent": consent, "device_scopes": scopes},
        "expected": _decision_json(decision),
    }


def authorize_cases() -> list[dict[str, Any]]:
    rng = random.Random(20261016)  # noqa: S311 - a fixed seed for a reproducible fixture
    cases: list[dict[str, Any]] = []
    names = list(DEFAULT_REGISTRY.names())
    # Names that are forbidden, unknown or odd.
    extra = [
        "finance.transfer",
        "finance.pay.rent",
        "shell.run",
        "files.delete",
        "email.send",
        "system.install",
        "Finance.Purchase",
        "no.such.thing",
        "",
        "assistant",
        "windows.ui.invoke",
    ]
    for index, name in enumerate(names + extra):
        capability = DEFAULT_REGISTRY.get(name)
        base = _sample(capability.args_schema) if capability else {}
        arg_sets = _variants(base, capability.args_schema) if capability else [{}, {"x": 1}]
        for variant, args in enumerate(arg_sets):
            for state_kind in range(3):
                approval = None
                if state_kind == 1:
                    approval = {
                        "proposal_id": "prop-0001",
                        "args_hash": None,
                        "target_device": "phone-1",
                        "user": "owner",
                        "via": "tap",
                        "expires_in_s": 60,
                    }
                if state_kind == 2:
                    approval = {
                        "proposal_id": "prop-0001",
                        "args_hash": None,
                        "target_device": "pc-1",
                        "user": "owner",
                        "via": "click",
                        "expires_in_s": 60,
                    }
                cases.append(
                    _run(
                        name,
                        args,
                        [],
                        (),
                        approval,
                        {},
                        None,
                        False,
                        "pc-1" if state_kind == 2 else "phone-1",
                        f"{index}.{variant}.{state_kind}",
                    )
                )
    # Approvals: every way they can be wrong, against a T2 capability.
    t2 = [n for n in names if (c := DEFAULT_REGISTRY.get(n)) and c.tier.value == "T2"]
    for n in t2:
        capability = DEFAULT_REGISTRY.get(n)
        args = _sample(capability.args_schema)
        target = "pc-1" if capability.confirm_on == "target" else "phone-1"
        good = {
            "proposal_id": "prop-0001",
            "args_hash": None,
            "target_device": target,
            "user": "owner",
            "via": "click",
            "expires_in_s": 30,
        }
        mutations = {
            "good": {},
            "speech": {"via": "speech"},
            "voice": {"via": "voice"},
            "tap": {"via": "tap"},
            "expired": {"expires_in_s": -1},
            "expires_now": {"expires_in_s": 0},
            "other_proposal": {"proposal_id": "prop-9999"},
            "other_args": {"args_hash": "0" * 64},
            "other_user": {"user": "guest"},
            "wrong_device": {"target_device": "somewhere-else"},
            "other_screen": {"target_device": "pc-1" if target == "phone-1" else "phone-1"},
        }
        for label, change in mutations.items():
            cases.append(
                _run(
                    n,
                    args,
                    [],
                    (),
                    {**good, **change},
                    {},
                    None,
                    False,
                    "pc-1",
                    f"approval.{n}.{label}",
                )
            )
    # Entities, unresolved words, consent and scopes, drawn from a seed over all capabilities.
    for i in range(400):
        n = rng.choice(names)
        capability = DEFAULT_REGISTRY.get(n)
        args = _sample(capability.args_schema)
        entities = rng.choice(ENTITY_SETS)
        unresolved = rng.choice([(), (), (), ("tomorrow",), ("morning", "later")])
        consent = rng.choice(
            [{}, {"finance": True}, {"health": False}, {"memory": True, "personal": True}]
        )
        scopes = rng.choice(
            [None, None, ["finance"], ["any"], ["kernel"], ["windows", "memory"], []]
        )
        approval = rng.choice(
            [
                None,
                None,
                {
                    "proposal_id": "prop-0001",
                    "args_hash": None,
                    "target_device": "phone-1",
                    "user": "owner",
                    "via": "tap",
                    "expires_in_s": 45,
                },
            ]
        )
        cases.append(
            _run(
                n,
                args,
                list(entities),
                tuple(unresolved),
                approval,
                consent,
                scopes,
                rng.random() < 0.5,
                rng.choice(["phone-1", "pc-1"]),
                f"mix.{i}",
            )
        )
    return cases


def hash_cases() -> list[dict[str, Any]]:
    sets: list[dict[str, Any]] = [
        {},
        {"a": 1},
        {"b": 2, "a": 1},
        {"amount": 12, "currency": "USD", "category": "Food · Dining", "note": "lunch"},
        {"amount": 12.5, "currency": "USD", "category": "x", "note": "y"},
        {"amount": 12.0, "note": "whole"},
        {"amount": -0.0, "note": "signed zero"},
        {"amount": 0.0001, "note": "small fixed decimal"},
        {"amount": 1e-7, "note": "small exponent"},
        {"amount": 12345678.9, "note": "large fixed decimal"},
        {"amount": 1e16, "note": "large exponent"},
        {"note": 'quote " backslash \\ newline \n tab \t'},
        {"note": "unicode é ü 日本語 🎉"},
        {"nested": {"z": [1, 2, {"k": True}], "a": None}},
        {"flag": False, "n": 0, "neg": -3, "big": 1234567890123},
        {"note": "control \u0001 char"},
        {"empty": "", "list": []},
    ]
    return [
        {"args": a, "hash": policy.args_hash(a), "canonical": policy.canonical_args(a)}
        for a in sets
    ]


RULE_TEXTS = [
    "what's on today",
    "what is on my schedule for today",
    "show me my day",
    "today",
    "my day",
    "how much did I spend this month",
    "how much have i spent",
    "spending summary last week",
    "what did I spend this year",
    "show me my spending",
    "show spending",
    "remember that the wifi code is 4471",
    "note buy milk",
    "make a note call the dentist",
    "please remember dentist at 3",
    "remember a",
    "what did I say about the wifi",
    "do you remember the wifi code",
    "recall the dentist",
    "remind me what I said about taxes",
    "stop",
    "Stop talking.",
    "please stop",
    "be quiet",
    "hush",
    "enough",
    "stop the music",
    "do not stop believing",
    "repeat that",
    "say that again",
    "what did you say?",
    "come again",
    "repeat after me hello",
    "undo",
    "undo that",
    "undo the last expense",
    "take that back",
    "revert that",
    "undo my commit",
    "pay my rent",
    "transfer 50 dollars to sam",
    "send money to mum",
    "wire cash",
    "buy a coffee",
    "order me a pizza",
    "log into my bank",
    "bank password",
    "what dose of ibuprofen",
    "how many pills can I take",
    "run a command",
    "open powershell",
    "delete my files",
    "wipe all the photos",
    "send an email to sam",
    "email sam",
    "write a message to sam",
    "hello there",
    "what is the weather",
    "tell me a joke",
    "",
    "   ",
    "...",
    "today is a good day",
    "how much did i spend on food",
    "spending",
    "remember",
    "note",
    "recall",
    "PAY MY RENT",
    "Stop.",
    "UNDO",
    "How Much Did I Spend This Month?",
    "café remember that naïve plan works",
    "remember " + "x" * 600,
    "recall " + "é" * 600,
]


def rules_cases() -> list[dict[str, Any]]:
    out = []
    for text in RULE_TEXTS:
        hit = parse(text, RESOLVER)
        if hit is not None and hit.capability.startswith("windows.app."):
            continue  # the app rules are Windows-only; the phone has its own (C2)
        expected = None if hit is None else {"capability": hit.capability, "args": hit.args}
        out.append({"text": text, "expected": expected})
    return out


def refusal_cases() -> list[dict[str, Any]]:
    reasons = [
        "FORBIDDEN_CAPABILITY",
        "UNRESOLVED_TERMS",
        "LOW_EVIDENCE",
        "AMBIGUOUS_ENTITY",
        "APPROVAL_REQUIRED",
        "INVALID_ARGS",
        "UNKNOWN_CAPABILITY",
        "CONSENT_REQUIRED",
        "STATE_MISMATCH",
        "DENIED_TIER",
        "OK",
    ]
    capabilities = [
        "finance.transfer",
        "health.dose",
        "shell.run",
        "email.send",
        "files.delete",
        "today.get",
        "",
    ]
    return [
        {"reason": r, "capability": c, "text": outcomes.refusal_text(r, c)}
        for r in reasons
        for c in capabilities
    ]


def build() -> dict[str, Any]:
    return {
        "authorize-cases.json": {
            "registry_revision": DEFAULT_REGISTRY.revision,
            "now": NOW.isoformat().replace("+00:00", "Z"),
            "cases": authorize_cases(),
            "hashes": hash_cases(),
        },
        "rules-cases.json": {"cases": rules_cases(), "refusals": refusal_cases()},
    }


def main() -> int:
    files = build()
    stale = False
    for name, data in files.items():
        text = json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"
        target = FIXTURES / name
        if "--check" in sys.argv:
            current = (
                target.read_text(encoding="utf-8").replace("\r\n", "\n") if target.exists() else ""
            )
            if current != text:
                print(f"{name} is stale; run tools/ci/make_policy_cases.py")
                stale = True
        else:
            target.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {target} ({len(text)} bytes)")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
