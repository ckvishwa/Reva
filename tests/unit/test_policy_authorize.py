"""B3a: registry, argument validator and the pure authorize() (AR-LANG-007, AR-AGT-001..006)."""

from __future__ import annotations

import ast
import json
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from reva_core.policy import schema
from reva_core.policy.authorize import (
    AMBIGUITY_MARGIN,
    Approval,
    AuthState,
    Entity,
    Proposal,
    Resolution,
    args_hash,
    authorize,
    canonical_args,
)
from reva_core.policy.registry import DEFAULT_REGISTRY, Registry, Tier, load_registry

ROOT = Path(__file__).resolve().parents[2]
EMPTY_SCHEMA = {"type": "object", "additionalProperties": False, "required": [], "properties": {}}
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
DECISION_SCHEMA = json.loads(
    (ROOT / "contracts" / "authorization-decision.schema.json").read_text("utf-8")
)


def prop(capability="windows.app.open", args=None, **kwargs) -> Proposal:
    if args is None:
        args = {"app_key": "notepad"}
    return Proposal(
        proposal_id=kwargs.pop("proposal_id", "act-00000001"),
        capability=capability,
        args=args,
        **kwargs,
    )


def state(**kwargs) -> AuthState:
    return AuthState(now=kwargs.pop("now", NOW), **kwargs)


def approval_for(p: Proposal, **overrides) -> Approval:
    base = dict(
        proposal_id=p.proposal_id,
        args_hash=args_hash(p.args),
        target_device=p.target_device,
        user="owner",
        via="click",
        expires_at=NOW + timedelta(minutes=1),
    )
    base.update(overrides)
    return Approval(**base)


def decide(p: Proposal, s: AuthState | None = None):
    decision = authorize(p, s or state())
    jsonschema.validate(decision.to_dict(), DECISION_SCHEMA)
    return decision


# ------------------------------------------------------------------------- registry


def test_the_packaged_registry_and_schema_equal_the_contract_copies() -> None:
    for name in ("capability-registry.v2.json", "authorization-decision.schema.json"):
        contract = (ROOT / "contracts" / name).read_bytes().replace(b"\r\n", b"\n")
        packaged = (ROOT / "reva_core" / "policy" / "data" / name).read_bytes()
        assert contract == packaged.replace(b"\r\n", b"\n"), name


def test_every_capability_has_a_supported_schema_and_a_known_tier() -> None:
    assert len(DEFAULT_REGISTRY.names()) == 34
    for name in DEFAULT_REGISTRY.names():
        capability = DEFAULT_REGISTRY.get(name)
        assert capability is not None
        schema.check_supported(capability.args_schema)
        assert capability.tier in (Tier.T0, Tier.T1, Tier.T2)
        if capability.tier == Tier.T2:
            assert capability.confirm_on in ("origin", "target"), name


def test_the_registry_has_no_forbidden_capability_and_refuses_to_load_one(tmp_path: Path) -> None:
    for name in DEFAULT_REGISTRY.names():
        assert not DEFAULT_REGISTRY.is_forbidden(name), name
    document = json.loads((ROOT / "contracts" / "capability-registry.v2.json").read_text("utf-8"))
    for forbidden in ("finance.transfer", "shell.run", "files.delete", "email.send", "health.dose"):
        bad = {**document, "capabilities": [*document["capabilities"], {
            "capability": forbidden, "device": "any", "tier": "T1", "confirm_on": None,
            "idempotent": True, "evidence_kind": "none",
            "args_schema": EMPTY_SCHEMA,
        }]}  # fmt: skip
        path = tmp_path / f"{forbidden}.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="forbidden"):
            load_registry(path)


def test_a_registry_that_uses_a_keyword_the_validator_ignores_is_refused() -> None:
    document = json.loads((ROOT / "contracts" / "capability-registry.v2.json").read_text("utf-8"))
    document["capabilities"][0]["args_schema"]["properties"]["x"] = {"type": "string", "oneOf": []}
    with pytest.raises(schema.UnsupportedSchema):
        Registry(document)


# ---------------------------------------------------------------- argument validation


@pytest.mark.parametrize(
    ("value", "spec", "ok"),
    [
        (
            {"a": "x"},
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
            },
            True,
        ),
        ({"a": 1}, {"type": "object", "properties": {"a": {"type": "string"}}}, False),
        ({}, {"type": "object", "required": ["a"], "properties": {"a": {}}}, False),
        (
            {"a": 1, "b": 2},
            {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
            False,
        ),
        ("abc", {"type": "string", "maxLength": 2}, False),
        ("ab", {"type": "string", "minLength": 3}, False),
        ("USD", {"type": "string", "pattern": "^[A-Z]{3}$"}, True),
        ("usd", {"type": "string", "pattern": "^[A-Z]{3}$"}, False),
        (5, {"type": "number", "minimum": 6}, False),
        (5, {"type": "number", "maximum": 4}, False),
        (True, {"type": "number"}, False),
        (True, {"type": "integer"}, False),
        (float("nan"), {"type": "number"}, False),
        (float("inf"), {"type": "number"}, False),
        ("x", {"enum": ["y"]}, False),
        ("2026-10-15T12:00:00Z", {"type": "string", "format": "date-time"}, True),
        ("tomorrow", {"type": "string", "format": "date-time"}, False),
        (None, {"type": "string"}, False),
    ],
)
def test_the_validator_enforces_each_keyword(value, spec, ok: bool) -> None:
    assert (schema.validate(value, spec) == []) is ok


def test_deeply_nested_input_is_refused_not_walked_forever() -> None:
    nested: dict = {}
    cursor = nested
    spec: dict = {"type": "object", "properties": {}}
    spec_cursor = spec
    for _ in range(30):
        cursor["a"] = {}
        cursor = cursor["a"]
        spec_cursor["properties"]["a"] = {"type": "object", "properties": {}}
        spec_cursor = spec_cursor["properties"]["a"]

    assert schema.validate(nested, spec)


# ------------------------------------------------------------------------ authorize


def test_a_t1_open_is_allowed_with_a_valid_decision_document() -> None:
    decision = decide(prop())

    assert decision.allowed and decision.reason == "OK" and decision.tier == "T1"
    assert decision.to_dict()["authorizer_version"] == "1.0.0"


def test_t0_information_is_allowed() -> None:
    assert decide(prop("today.get", {})).tier == "T0"
    assert decide(prop("finance.summary", {"period": "month"})).allowed


@pytest.mark.parametrize(
    "name",
    ["finance.pay", "finance.transfer", "finance.purchase", "finance.bank_login", "health.dose",
     "health.diagnose", "shell.run", "shell.", "files.delete", "email.send", "system.install",
     "FINANCE.TRANSFER", "Shell.Exec"],
)  # fmt: skip
def test_forbidden_capabilities_are_refused_by_name_and_never_allowed(name: str) -> None:
    decision = decide(prop(name, {"amount": 500}))

    assert not decision.allowed and decision.reason == "FORBIDDEN_CAPABILITY"


@pytest.mark.parametrize(
    "name", ["", "windows.app.format", "finance.refund", "x", "windows.app.open "]
)
def test_an_unregistered_name_is_unknown(name: str) -> None:
    decision = decide(prop(name))

    assert not decision.allowed and decision.reason == "UNKNOWN_CAPABILITY"


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"app_key": "regedit"},
        {"app_key": "notepad", "extra": 1},
        {"app_key": 5},
        {"app_key": ["notepad"]},
        {"tier": "T0", "app_key": "notepad"},
        {"app_key": "notepad", "args": "-rf /"},
    ],
)
def test_arguments_must_fit_the_schema_exactly(args: dict) -> None:
    decision = decide(prop(args=args))

    assert not decision.allowed and decision.reason == "INVALID_ARGS"
    assert decision.problems


def test_arguments_that_are_not_an_object_are_invalid() -> None:
    decision = authorize(prop(args=["notepad"]), state())  # type: ignore[arg-type]

    assert decision.reason == "INVALID_ARGS"


def test_the_tier_comes_from_the_registry_never_from_the_proposal() -> None:
    # Nothing in a proposal can name a tier; an attempt to smuggle one in is invalid arguments.
    sneaky = prop("windows.app.close", {"app_key": "notepad", "tier": "T0"})

    assert decide(sneaky).reason == "INVALID_ARGS"
    assert decide(prop("windows.app.close", {"app_key": "notepad"})).tier == "T2"


def test_untrusted_resolution_asks_instead_of_acting() -> None:
    for resolution in (Resolution.LEXICAL, Resolution.FUZZY, Resolution.VECTOR):
        entity = Entity("app", "note pad", resolution, score=0.9, candidates=("notepad",))
        decision = decide(prop(entities=(entity,)))

        assert decision.reason == "LOW_EVIDENCE" and not decision.allowed
        assert decision.unresolved == ("note pad",)
        assert decision.clarification == {"question_template": "which_app", "options": ["notepad"]}


def test_an_entity_with_no_resolution_is_unresolved_terms() -> None:
    decision = decide(prop(entities=(Entity("app", "the thing", Resolution.NONE),)))

    assert decision.reason == "UNRESOLVED_TERMS" and decision.unresolved == ("the thing",)


@pytest.mark.parametrize(
    "resolution", [Resolution.EXACT, Resolution.ALIAS, Resolution.CONFIRMED, Resolution.TYPED_VALUE]
)
def test_trusted_resolutions_pass(resolution: Resolution) -> None:
    assert decide(prop(entities=(Entity("app", "notepad", resolution),))).allowed


def test_leftover_content_words_block_the_action() -> None:
    decision = decide(prop(unresolved_terms=("tomorrow", "mum")))

    assert decision.reason == "UNRESOLVED_TERMS" and decision.unresolved == ("tomorrow", "mum")
    assert decision.clarification == {"question_template": "unresolved_terms"}


def test_two_close_candidates_ask_which_one_with_at_most_three_options() -> None:
    entity = Entity(
        "app",
        "code",
        Resolution.EXACT,
        margin=AMBIGUITY_MARGIN - 0.01,
        candidates=("vscode", "vs", "visual", "extra"),
    )
    decision = decide(prop(entities=(entity,)))

    assert decision.reason == "AMBIGUOUS_ENTITY"
    assert decision.clarification == {
        "question_template": "ambiguous_entity",
        "options": ["vscode", "vs", "visual"],
    }
    clear = Entity(
        "app", "code", Resolution.EXACT, margin=AMBIGUITY_MARGIN + 0.01, candidates=("vscode", "vs")
    )
    assert decide(prop(entities=(clear,))).allowed
    unknown_margin = Entity("app", "code", Resolution.EXACT, margin=None, candidates=("a", "b"))
    assert decide(prop(entities=(unknown_margin,))).reason == "AMBIGUOUS_ENTITY"


def test_the_order_of_checks_is_fixed() -> None:
    bad_everything = prop(
        "windows.app.open",
        {"app_key": "regedit"},
        entities=(Entity("app", "x", Resolution.NONE),),
        unresolved_terms=("y",),
        hosted_origin=True,
    )
    assert decide(bad_everything).reason == "INVALID_ARGS"  # args before entities
    no_args_problem = replace(bad_everything, args={"app_key": "notepad"})
    assert decide(no_args_problem).reason == "UNRESOLVED_TERMS"  # entity evidence before the rest
    assert (
        decide(prop("shell.run", {})).reason == "FORBIDDEN_CAPABILITY"
    )  # forbidden before unknown


# ---------------------------------------------------------------------------- T2


def close() -> Proposal:
    return prop("windows.app.close", {"app_key": "notepad"})


def test_t2_without_an_approval_asks_for_one() -> None:
    decision = decide(close())

    assert not decision.allowed and decision.reason == "APPROVAL_REQUIRED" and decision.tier == "T2"


@pytest.mark.parametrize("via", ["click", "tap"])
def test_a_click_or_tap_on_the_right_device_approves(via: str) -> None:
    p = close()

    decision = decide(p, state(approval=approval_for(p, via=via)))

    assert decision.allowed and decision.reason == "OK"


@pytest.mark.parametrize("via", ["speech", "voice", "", "enter", "api"])
def test_a_spoken_yes_or_anything_but_a_click_or_tap_is_not_an_approval(via: str) -> None:
    p = close()

    decision = decide(p, state(approval=approval_for(p, via=via)))

    assert not decision.allowed and decision.reason == "APPROVAL_REQUIRED"


def test_an_expired_approval_does_not_count() -> None:
    p = close()

    stale = decide(p, state(approval=approval_for(p, expires_at=NOW)))
    old = decide(p, state(approval=approval_for(p, expires_at=NOW - timedelta(seconds=1))))

    assert stale.reason == old.reason == "APPROVAL_REQUIRED"


@pytest.mark.parametrize(
    "override",
    [
        {"proposal_id": "act-99999999"},
        {"args_hash": args_hash({"app_key": "spotify"})},
        {"args_hash": "0" * 64},
        {"user": "someone-else"},
        {"target_device": "phone-0001"},
    ],
)
def test_an_approval_for_anything_else_is_a_state_mismatch(override: dict) -> None:
    p = close()

    decision = decide(p, state(approval=approval_for(p, **override)))

    assert not decision.allowed and decision.reason == "STATE_MISMATCH"


def test_substituting_the_arguments_after_approval_is_caught() -> None:
    approved = close()
    approval = approval_for(approved)
    substituted = replace(approved, args={"app_key": "chrome"})

    assert decide(substituted, state(approval=approval)).reason == "STATE_MISMATCH"


def test_origin_confirmation_needs_the_origin_device_and_target_confirmation_the_target() -> None:
    origin_t2 = prop("finance.add_transaction",
        {"amount": 12, "currency": "USD", "category": "food", "note": "lunch"},
        origin_device="pc-0001", target_device="pc-0001")  # fmt: skip
    assert decide(
        origin_t2, state(approval=approval_for(origin_t2, target_device="pc-0001"))
    ).allowed
    on_phone = prop(
        "windows.app.close",
        {"app_key": "notepad"},
        origin_device="phone-1",
        target_device="pc-0001",
    )
    # The target is the PC: a tap on the phone is not enough, the click must be on the PC.
    assert (
        decide(on_phone, state(approval=approval_for(on_phone, target_device="phone-1"))).reason
        == "STATE_MISMATCH"
    )
    assert decide(on_phone, state(approval=approval_for(on_phone, target_device="pc-0001"))).allowed


def test_a_t1_action_needs_no_approval_and_an_unneeded_one_changes_nothing() -> None:
    p = prop()
    assert decide(p).allowed
    assert decide(p, state(approval=approval_for(p, via="speech"))).allowed


# ------------------------------------------------------------- consent and scope


def test_a_hosted_model_proposal_needs_the_domains_consent() -> None:
    p = prop("finance.summary", {"period": "month"}, hosted_origin=True)

    assert decide(p).reason == "CONSENT_REQUIRED"
    assert decide(p, state(consent={"finance": False})).reason == "CONSENT_REQUIRED"
    assert decide(p, state(consent={"finance": True})).allowed
    assert decide(
        prop("finance.summary", {"period": "month"})
    ).allowed  # local proposals are unaffected


def test_a_remote_device_only_reaches_what_its_grant_covers() -> None:
    p = prop("finance.summary", {"period": "week"})

    assert decide(p, state(device_scopes=frozenset({"finance"}))).allowed
    assert decide(p, state(device_scopes=frozenset({"health"}))).reason == "CONSENT_REQUIRED"
    assert decide(prop(), state(device_scopes=frozenset({"finance"}))).reason == "CONSENT_REQUIRED"
    assert decide(prop(), state(device_scopes=frozenset({"windows"}))).allowed


# --------------------------------------------------------------------------- T3


def test_a_t3_capability_is_denied() -> None:
    document = json.loads((ROOT / "contracts" / "capability-registry.v2.json").read_text("utf-8"))
    document["capabilities"].append({
        "capability": "windows.risky.thing", "device": "windows", "tier": "T3", "confirm_on": None,
        "idempotent": False, "evidence_kind": "none",
        "args_schema": EMPTY_SCHEMA,
    })  # fmt: skip
    registry = Registry(document)

    decision = authorize(prop("windows.risky.thing", {}), state(), registry)

    assert not decision.allowed and decision.reason == "DENIED_TIER" and decision.tier == "T3"


# ------------------------------------------------------- purity and stability


def test_the_same_inputs_always_give_the_same_decision() -> None:
    p = close()
    s = state(approval=approval_for(p))

    assert authorize(p, s) == authorize(p, s) == authorize(p, s)
    assert json.dumps(decide(p, s).to_dict()) == json.dumps(decide(p, s).to_dict())


def test_authorize_changes_nothing_it_is_given() -> None:
    args = {"app_key": "notepad"}
    p = prop(args=args)
    s = state()

    authorize(p, s)

    assert args == {"app_key": "notepad"} and p.args == {"app_key": "notepad"}


def test_authorize_imports_no_model_network_file_or_clock_machinery() -> None:
    tree = ast.parse((ROOT / "reva_core" / "policy" / "authorize.py").read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    forbidden_modules = {
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "sqlite3",
        "asyncio",
        "random",
        "time",
        "os",
        "pathlib",
        "anthropic",
        "ollama",
        "litellm",
    }

    assert not imported & forbidden_modules, imported & forbidden_modules
    assert not called & {"open", "print", "input", "exec", "eval", "compile", "__import__"}
    clock_reads = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id in ("datetime", "date", "time")
        and n.attr in ("now", "utcnow", "today")
    ]
    assert not clock_reads  # the caller passes the time in `AuthState.now`


def test_canonical_args_ignore_key_order_and_spacing() -> None:
    assert (
        canonical_args({"b": 1, "a": "é"})
        == canonical_args({"a": "é", "b": 1})
        == '{"a":"é","b":1}'
    )
    assert args_hash({"b": 1, "a": 2}) == args_hash({"a": 2, "b": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})


# ------------------------------------------------------------------- fuzz


def _random_value(rng: random.Random, depth: int = 0):
    kinds = (
        ["str", "int", "float", "bool", "none", "list", "dict"]
        if depth < 2
        else ["str", "int", "none"]
    )
    kind = rng.choice(kinds)
    if kind == "str":
        return rng.choice(
            [
                "",
                "notepad",
                "chrome",
                "USD",
                "x" * rng.randint(0, 700),
                "\x00",
                "../../etc",
                "'; DROP TABLE",
            ]
        )
    if kind == "int":
        return rng.randint(-5, 10**9)
    if kind == "float":
        return rng.choice([0.0, -1.5, 1e308, float("nan"), float("inf"), 12.5])
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "none":
        return None
    if kind == "list":
        return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {
        rng.choice(["app_key", "amount", "x", "tier"]): _random_value(rng, depth + 1)
        for _ in range(rng.randint(0, 3))
    }


def test_random_proposals_never_crash_and_a_t2_action_is_never_allowed_without_an_approval() -> (
    None
):
    rng = random.Random(20261015)  # noqa: S311 - test data, not security
    names = [*DEFAULT_REGISTRY.names(), "finance.transfer", "shell.run", "nope", "", "x" * 300]
    for _ in range(4000):
        p = Proposal(
            proposal_id=f"act-{rng.randint(0, 99999999):08d}",
            capability=rng.choice(names),
            args=_random_value(rng)
            if rng.random() < 0.4
            else {rng.choice(["app_key", "amount", "period", "query"]): _random_value(rng)},
            entities=(Entity("app", "x", rng.choice(list(Resolution))),)
            if rng.random() < 0.3
            else (),
            unresolved_terms=("w",) if rng.random() < 0.1 else (),
            hosted_origin=rng.random() < 0.3,
        )
        decision = authorize(p, state(consent={"finance": rng.random() < 0.5}))
        jsonschema.validate(decision.to_dict(), DECISION_SCHEMA)
        capability = DEFAULT_REGISTRY.get(p.capability)
        if decision.allowed:
            assert capability is not None and capability.tier in (Tier.T0, Tier.T1), p.capability
            assert not DEFAULT_REGISTRY.is_forbidden(p.capability)
