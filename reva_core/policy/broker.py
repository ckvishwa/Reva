"""The action broker (ARD-600 section 3): propose -> authorize -> approve -> grant -> outcome.

A model may *propose*. The broker is the only place a proposal becomes permission, and it does that
only through the pure `authorize()`. Executors *act*, and only on a signed grant. REVA *speaks*
about an action only from the outcome an executor reported with evidence, through templates
(`language/outcomes.py`): a status of `verified` needs evidence of the kind the registry expects for
that capability, otherwise it is recorded as `unknown`. Nothing a model writes can reach the
outcome.

Every step is appended to the action ledger.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from reva_core.language import outcomes
from reva_core.policy.authorize import (
    Approval,
    AuthorizationDecision,
    AuthState,
    Proposal,
    args_hash,
    authorize,
)
from reva_core.policy.grants import GRANT_TTL, Grant, GrantSigner, utc_iso
from reva_core.policy.ledger import ActionLedger, redact_args
from reva_core.policy.registry import DEFAULT_REGISTRY, Registry, Tier
from reva_core.shared.ids import new_id

logger = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(minutes=2)
MAX_OPEN = 64
MAX_KEPT = 1000  # finished actions kept in memory; the ledger keeps them all
MAX_EVIDENCE_REF = 200

# Statuses an executor may report, in the order an action moves through them.
OUTCOME_ORDER = {
    "attempted": 0,
    "observed": 1,
    "verified": 2,
    "failed": 2,
    "unknown": 2,
    "denied": 2,
}
TERMINAL = frozenset({"verified", "failed", "unknown", "denied"})


class BrokerFull(Exception):
    """Too many actions are waiting; the caller should retry later."""


class UnknownAction(KeyError):
    pass


class GrantMismatch(PermissionError):
    """An outcome came with a grant that is not the one issued for this action."""


@dataclass
class ActionRecord:
    action_id: str
    proposal: Proposal
    user: str
    tier: Tier
    # allowed, awaiting_approval, refused, denied, expired, granted, attempted, observed,
    # verified, failed, unknown
    status: str
    reason: str
    created: datetime
    deadline: datetime | None = None
    grant: Grant | None = None
    signature: str | None = None
    evidence: dict[str, Any] | None = None
    note: str | None = None


@dataclass(frozen=True)
class ExecutionOrder:
    """What an executor receives: the signed grant and exactly what to do."""

    grant: Grant
    signature: str
    capability: str
    args: Mapping[str, Any]
    target_device: str


@dataclass(frozen=True)
class ActionView:
    action_id: str
    capability: str
    tier: str
    status: str
    reason: str
    target_device: str
    created: str
    speak: str | None  # the one sentence REVA may say now, or None
    clarification: dict[str, Any] | None = None
    order: ExecutionOrder | None = None
    deadline: str | None = None
    evidence_kind: str | None = None
    prompt: str | None = None  # the confirm-card sentence while the action awaits a click


# Runs a granted order inside Core (the Kernel executor). Returns (status, evidence).
CoreExecutor = Callable[["ExecutionOrder"], tuple[str, Mapping[str, Any] | None]]
Listener = Callable[["ActionView"], None]


@dataclass
class Broker:
    signer: GrantSigner
    ledger: ActionLedger
    registry: Registry = DEFAULT_REGISTRY
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    approval_ttl: timedelta = APPROVAL_TTL
    # The app keys currently allowed (built-in plus owner-approved), and their display names.
    app_keys: Callable[[], tuple[str, ...]] | None = None
    app_names: Callable[[], Mapping[str, str]] | None = None
    # Capabilities Core carries out itself (the Kernel), keyed by capability name.
    core_executors: dict[str, CoreExecutor] = field(default_factory=dict)
    _records: dict[str, ActionRecord] = field(default_factory=dict)
    _decisions: dict[str, AuthorizationDecision] = field(default_factory=dict)
    _listeners: list[Listener] = field(default_factory=list)
    _registry_cache: tuple[tuple[str, ...], Registry] | None = None

    def subscribe(self, listener: Listener) -> None:
        """Called with the new view after an action changes outside the request that made it
        (an executor's report, a timeout). A listener must never raise or block."""
        self._listeners.append(listener)

    def _reg(self) -> Registry:
        if self.app_keys is None:
            return self.registry
        keys = tuple(self.app_keys())
        if self._registry_cache is None or self._registry_cache[0] != keys:
            self._registry_cache = (keys, self.registry.with_app_keys(keys))
        return self._registry_cache[1]

    def _notify(self, view: ActionView) -> None:
        for listener in list(self._listeners):
            try:
                listener(view)
            except Exception:  # noqa: BLE001 - one broken listener must not undo an outcome
                logger.warning("action listener failed", exc_info=True)

    # ---------------------------------------------------------------------- propose

    def propose(
        self,
        proposal: Proposal,
        *,
        user: str = "owner",
        consent: Mapping[str, bool] | None = None,
        device_scopes: frozenset[str] | None = None,
    ) -> ActionView:
        now = self.clock()
        self._expire(now)
        self._forget_old()
        existing = self._records.get(proposal.proposal_id)
        if existing is not None:
            # The same id again changes nothing; a different request under that id is refused.
            if args_hash(existing.proposal.args) != args_hash(proposal.args) or (
                existing.proposal.capability != proposal.capability
            ):
                return self._refuse_collision(proposal, now)
            return self._view(existing)
        if (
            sum(1 for r in self._records.values() if r.status in ("awaiting_approval", "granted"))
            >= MAX_OPEN
        ):
            raise BrokerFull("too many actions are waiting")

        decision = authorize(
            proposal,
            AuthState(now=now, user=user, consent=consent or {}, device_scopes=device_scopes),
            self._reg(),
        )
        capability = self._reg().get(proposal.capability)
        tier = (
            Tier(decision.tier) if decision.tier else (capability.tier if capability else Tier.T3)
        )
        record = ActionRecord(
            action_id=proposal.proposal_id,
            proposal=proposal,
            user=user,
            tier=tier,
            status="refused",
            reason=decision.reason,
            created=now,
        )
        self._records[record.action_id] = record
        self._decisions[record.action_id] = decision
        self._log(
            record,
            "proposed",
            {
                "capability": proposal.capability,
                "tier": tier.value if capability else None,
                "source": proposal.source,
                "target_device": proposal.target_device,
                "args": redact_args(capability, dict(proposal.args)) if capability else {},
                "reason": decision.reason,
                "allowed": decision.allowed,
            },
        )

        if decision.allowed:
            if tier == Tier.T0:
                record.status = "allowed"  # Core answers from its own data; nothing to execute
            else:
                self._issue_grant(record, now)
        elif decision.reason == "APPROVAL_REQUIRED":
            record.status = "awaiting_approval"
            record.deadline = now + self.approval_ttl
            self._log(record, "awaiting_approval", {"deadline": utc_iso(record.deadline)})
        else:
            record.status = "refused"
            self._log(record, "refused", {"reason": decision.reason})
        return self._view(record, decision)

    # ---------------------------------------------------------------------- approval

    def approve(self, action_id: str, *, via: str, device: str, user: str = "owner") -> ActionView:
        """A click or tap on `device`. A spoken yes or the wrong screen is rejected."""
        now = self.clock()
        self._expire(now)
        record = self._get(action_id)
        if record.status != "awaiting_approval":
            return self._view(record)
        assert record.deadline is not None
        approval = Approval(
            proposal_id=record.action_id,
            args_hash=args_hash(record.proposal.args),
            target_device=device,
            user=user,
            via=via,
            expires_at=record.deadline,
        )
        decision = authorize(
            record.proposal,
            AuthState(now=now, approval=approval, user=record.user),
            self._reg(),
        )
        if not decision.allowed:
            self._log(record, "approval_rejected", {"reason": decision.reason, "via": via})
            return self._view(record, decision)
        self._log(record, "approved", {"via": via, "device": device})
        self._issue_grant(record, now)
        view = self._view(record, decision)
        self._notify(view)
        return view

    def deny(self, action_id: str, *, via: str = "click") -> ActionView:
        record = self._get(action_id)
        if record.status == "awaiting_approval":
            record.status = "denied"
            record.reason = "DENIED_BY_USER"
            self._log(record, "denied", {"via": via})
            self._notify(self._view(record))
        return self._view(record)

    # ---------------------------------------------------------------------- outcome

    def report(
        self,
        action_id: str,
        grant_id: str,
        status: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> ActionView:
        """An executor says what happened. Only this can make REVA claim success."""
        record = self._get(action_id)
        if record.grant is None or not secrets.compare_digest(record.grant.grant_id, grant_id):
            raise GrantMismatch("that grant was not issued for this action")
        if status not in OUTCOME_ORDER:
            raise ValueError("unknown outcome status")
        if record.status in TERMINAL:
            return self._view(record)  # the first final answer stands
        current = OUTCOME_ORDER.get(record.status, -1)
        if OUTCOME_ORDER[status] < current:
            return self._view(record)  # a late "attempted" after "observed" is ignored
        view = self._apply_outcome(record, status, evidence)
        self._notify(view)
        return view

    def _apply_outcome(
        self, record: ActionRecord, status: str, evidence: Mapping[str, Any] | None
    ) -> ActionView:
        final = status
        note = None
        if status == "verified":
            capability = self._reg().get(record.proposal.capability)
            if capability is None or not _evidence_ok(capability.evidence_kind, evidence):
                final = "unknown"
                note = "verified was reported without evidence of the expected kind"
        record.status = final
        record.evidence = _clean_evidence(evidence)
        record.note = note
        self._log(
            record,
            "outcome",
            {
                "status": final,
                "reported": status,
                "evidence": record.evidence,
                "note": note,
            },
        )
        return self._view(record)

    # ---------------------------------------------------------------------- reading

    def get(self, action_id: str) -> ActionView:
        self._expire(self.clock())
        return self._view(self._get(action_id))

    def decision(self, action_id: str) -> AuthorizationDecision | None:
        return self._decisions.get(action_id)

    # ---------------------------------------------------------------------- internals

    def _get(self, action_id: str) -> ActionRecord:
        record = self._records.get(action_id)
        if record is None:
            raise UnknownAction(action_id)
        return record

    def _issue_grant(self, record: ActionRecord, now: datetime) -> None:
        proposal = record.proposal
        grant = Grant(
            grant_id=new_id(),
            action_id=record.action_id,
            capability=proposal.capability,
            args_hash=args_hash(proposal.args),
            target_device=proposal.target_device,
            actor=record.user,
            issued_at=utc_iso(now),
            expires_at=utc_iso(now + GRANT_TTL),
            idempotency_key=new_id(),
        )
        record.grant = grant
        record.signature = self.signer.sign(grant)
        record.status = "granted"
        record.deadline = None
        self._log(record, "granted", {"grant_id": grant.grant_id, "expires_at": grant.expires_at})
        executor = self.core_executors.get(proposal.capability)
        if executor is not None:
            self._run_in_core(record, executor)

    def _run_in_core(self, record: ActionRecord, executor: CoreExecutor) -> None:
        """The Kernel executor. It acts only on the grant the broker just signed, and what REVA says
        afterwards comes from the evidence it returns, exactly like a Windows executor's report."""
        assert record.grant is not None and record.signature is not None
        order = ExecutionOrder(
            record.grant,
            record.signature,
            record.proposal.capability,
            dict(record.proposal.args),
            record.proposal.target_device,
        )
        try:
            status, evidence = executor(order)
        except Exception:  # noqa: BLE001 - any failure is "failed", never a success claim
            logger.warning("core executor failed", exc_info=True)
            status, evidence = "failed", None
        self._apply_outcome(record, status, evidence)

    def _forget_old(self) -> None:
        if len(self._records) <= MAX_KEPT:
            return
        finished = [
            k
            for k, r in self._records.items()
            if r.status in TERMINAL | {"refused", "expired", "allowed"}
        ]
        for key in finished[: len(self._records) - MAX_KEPT]:
            self._records.pop(key, None)
            self._decisions.pop(key, None)

    def _expire(self, now: datetime) -> None:
        for record in self._records.values():
            if record.status == "awaiting_approval" and record.deadline and now >= record.deadline:
                record.status = "expired"
                record.reason = "APPROVAL_EXPIRED"
                self._log(record, "expired", {})
                self._notify(self._view(record))

    def _refuse_collision(self, proposal: Proposal, now: datetime) -> ActionView:
        decision = AuthorizationDecision(proposal.proposal_id, False, "STATE_MISMATCH")
        record = self._records[proposal.proposal_id]
        self._log(
            record, "refused", {"reason": "STATE_MISMATCH", "note": "same id, different request"}
        )
        return self._view(
            record, decision, override_status="refused", override_reason="STATE_MISMATCH"
        )

    def _log(self, record: ActionRecord, kind: str, payload: dict[str, Any]) -> None:
        self.ledger.append(record.action_id, kind, utc_iso(self.clock()), payload)

    def _view(
        self,
        record: ActionRecord,
        decision: AuthorizationDecision | None = None,
        *,
        override_status: str | None = None,
        override_reason: str | None = None,
    ) -> ActionView:
        decision = decision or self._decisions.get(record.action_id)
        status = override_status or record.status
        reason = override_reason or (
            decision.reason
            if decision and status in ("refused", "awaiting_approval")
            else record.reason
        )
        capability = self._reg().get(record.proposal.capability)
        order = None
        if status == "granted" and record.grant is not None and record.signature is not None:
            order = ExecutionOrder(
                record.grant,
                record.signature,
                record.proposal.capability,
                dict(record.proposal.args),
                record.proposal.target_device,
            )
        return ActionView(
            action_id=record.action_id,
            capability=record.proposal.capability,
            tier=record.tier.value,
            status=status,
            reason=reason,
            target_device=record.proposal.target_device,
            created=utc_iso(record.created),
            speak=self._speak(record, status, reason),
            clarification=decision.clarification if decision else None,
            order=order,
            deadline=utc_iso(record.deadline) if record.deadline else None,
            evidence_kind=capability.evidence_kind if capability else None,
            prompt=(
                outcomes.approval_prompt(
                    record.proposal.capability,
                    record.proposal.args,
                    self.app_names() if self.app_names is not None else None,
                )
                if status == "awaiting_approval"
                else None
            ),
        )

    def _speak(self, record: ActionRecord, status: str, reason: str) -> str | None:
        args = record.proposal.args
        capability = record.proposal.capability
        names = self.app_names() if self.app_names is not None else None
        if status in outcomes_statuses():
            return outcomes.outcome_text(status, capability, args, names=names)
        if status == "refused":
            return outcomes.refusal_text(reason, capability)
        if status == "awaiting_approval":
            return outcomes.NOT_APPROVED
        if status == "denied":
            return outcomes.DENIED
        if status == "expired":
            return outcomes.EXPIRED
        return None  # allowed or granted: nothing has happened yet, so nothing is claimed


def outcomes_statuses() -> frozenset[str]:
    return frozenset({"attempted", "observed", "verified", "failed", "unknown"})


def _evidence_ok(expected_kind: str, evidence: Mapping[str, Any] | None) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    ref = evidence.get("ref")
    if evidence.get("kind") != expected_kind or not isinstance(ref, str):
        return False
    if not 0 < len(ref) <= MAX_EVIDENCE_REF:
        return False
    shape = _REF_SHAPES.get(expected_kind)
    return shape is None or shape.fullmatch(ref) is not None


# What the reference must look like, so a bare "ok" is not evidence. An app open needs both the
# process and a top-level window; a close needs the process to be gone.
_REF_SHAPES = {
    "process_started": re.compile(r"pid:[0-9]{1,10} window:0x[0-9a-fA-F]{1,16}"),
    "process_exited": re.compile(r"pids?:[0-9]{1,10}(?:,[0-9]{1,10}){0,15} exited"),
    "kernel_event": re.compile(r"[A-Za-z0-9_-]{8,64}"),
}


def _clean_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(evidence, Mapping):
        return None
    out: dict[str, Any] = {}
    for key in ("kind", "ref"):
        value = evidence.get(key)
        if isinstance(value, str):
            out[key] = value[:MAX_EVIDENCE_REF]
    return out or None
