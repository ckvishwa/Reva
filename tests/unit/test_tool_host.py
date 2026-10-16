"""Execution boundary shared by local tools, plugins, and paired nodes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric import ec

from reva_core.policy.authorize import args_hash
from reva_core.policy.broker import ExecutionOrder
from reva_core.policy.grants import Grant, GrantSigner, GrantVerifier
from reva_core.policy.ledger import MemoryLedger
from reva_core.policy.registry import Registry


def _registry() -> Registry:
    return Registry(
        {
            "registry_revision": 1,
            "forbidden_capability_prefixes": [],
            "capabilities": [
                {
                    "capability": "test.echo",
                    "device": "windows",
                    "tier": "T2",
                    "confirm_on": "target",
                    "idempotent": False,
                    "evidence_kind": "test_output",
                    "args_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["text"],
                        "properties": {"text": {"type": "string", "maxLength": 100}},
                    },
                }
            ],
        }
    )


def _order(
    signer: GrantSigner,
    now: datetime,
    *,
    args: dict[str, str] | None = None,
    target: str = "pc",
) -> ExecutionOrder:
    actual_args = args or {"text": "hello"}
    grant = Grant(
        grant_id="grant-1",
        action_id="action-1",
        capability="test.echo",
        args_hash=args_hash(actual_args),
        target_device=target,
        actor="owner",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=1)).isoformat(),
        idempotency_key="once-1",
    )
    return ExecutionOrder(grant, signer.sign(grant), "test.echo", actual_args, target)


def test_signed_order_runs_registered_handler_once() -> None:
    from reva_core.execution.host import ToolHost

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    host = ToolHost(
        GrantVerifier(signer.public_key_pem()),
        _registry(),
        "pc",
        evidence_verifiers={"test.echo": lambda evidence: evidence["ref"] == "output-1"},
    )
    calls: list[str] = []

    def echo(args: dict[str, str]) -> dict[str, str]:
        calls.append(args["text"])
        return {"kind": "test_output", "ref": "output-1"}

    host.register("test.echo", echo)
    order = _order(signer, now)

    first = host.execute(order, now=now)
    second = host.execute(order, now=now)

    assert first.status == "verified"
    assert first.evidence == {"kind": "test_output", "ref": "output-1"}
    assert second.status == "denied"
    assert second.reason == "REPLAYED"
    assert calls == ["hello"]


def test_wrong_target_and_bad_signature_never_run_handler() -> None:
    from reva_core.execution.host import ToolHost

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    host = ToolHost(GrantVerifier(signer.public_key_pem()), _registry(), "pc")
    calls: list[str] = []
    host.register("test.echo", lambda args: calls.append(args["text"]) or None)
    remote_order = _order(signer, now, target="phone")
    valid_order = _order(signer, now)
    bad_order = ExecutionOrder(
        valid_order.grant, "invalid", valid_order.capability, valid_order.args, "pc"
    )

    assert host.execute(remote_order, now=now).reason == "WRONG_TARGET"
    assert host.execute(bad_order, now=now).reason == "MALFORMED"
    assert calls == []


def test_unregistered_or_invalid_arguments_never_run_handler() -> None:
    from reva_core.execution.host import ToolHost

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    host = ToolHost(GrantVerifier(signer.public_key_pem()), _registry(), "pc")

    assert host.execute(_order(signer, now), now=now).reason == "NO_HANDLER"
    calls: list[object] = []
    host.register("test.echo", lambda args: calls.append(args) or None)
    assert (
        host.execute(_order(signer, now, args={"text": "x", "extra": "y"}), now=now).reason
        == "INVALID_ARGS"
    )
    assert calls == []


def test_handler_failure_or_missing_evidence_never_claims_verified() -> None:
    from reva_core.execution.host import ToolHost

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    host = ToolHost(GrantVerifier(signer.public_key_pem()), _registry(), "pc")
    host.register("test.echo", lambda args: {"kind": "wrong", "ref": "output-1"})

    result = host.execute(_order(signer, now), now=now)
    assert result.status == "unknown"
    assert result.reason == "EVIDENCE_MISMATCH"


def test_broker_approval_is_required_before_tool_host_can_execute() -> None:
    from reva_core.execution.host import ToolHost
    from reva_core.policy.authorize import Proposal
    from reva_core.policy.broker import Broker

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    broker = Broker(signer=signer, ledger=MemoryLedger(), registry=_registry(), clock=lambda: now)
    host = ToolHost(
        GrantVerifier(signer.public_key_pem()),
        _registry(),
        "pc",
        evidence_verifiers={"test.echo": lambda evidence: evidence["ref"] == "output-1"},
    )
    calls: list[str] = []
    host.register(
        "test.echo",
        lambda args: calls.append(str(args["text"])) or {"kind": "test_output", "ref": "output-1"},
    )
    proposal = Proposal(
        proposal_id="action-1",
        capability="test.echo",
        args={"text": "hello"},
        target_device="pc",
    )

    pending = broker.propose(proposal)
    assert pending.status == "awaiting_approval"
    assert pending.order is None
    assert calls == []

    granted = broker.approve("action-1", via="click", device="pc")
    assert granted.status == "granted"
    assert granted.order is not None
    result = host.execute(granted.order, now=now)
    assert result.status == "verified"
    assert calls == ["hello"]


def test_handler_evidence_without_independent_verifier_is_only_observed() -> None:
    from reva_core.execution.host import ToolHost

    now = datetime(2026, 10, 16, tzinfo=UTC)
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    host = ToolHost(GrantVerifier(signer.public_key_pem()), _registry(), "pc")
    host.register("test.echo", lambda args: {"kind": "test_output", "ref": "claimed-output"})

    result = host.execute(_order(signer, now), now=now)

    assert result.status == "observed"
    assert result.reason == "UNVERIFIED_EVIDENCE"
