"""`authorize(proposal, state) -> AuthorizationDecision` (ARD-450 3.6, AR-LANG-007, AR-AGT-003/4/6).

Pure by construction: no model call, no I/O, no writes, no clock (the caller passes `now`), no
randomness. The same inputs always give the same decision with the same stable reason code, whether
the proposal came from the rule fast path or from the planner. Reason codes are the contract in
`contracts/authorization-decision.schema.json`; the order of checks below is part of the contract:

  1 forbidden capability   2 unknown capability   3 arguments fit the schema
  4 every entity has trustworthy evidence   5 no unresolved content words
  6 no competing candidate within the margin   7 an approval, if present, is bound to this proposal
  8 consent and device scope   9 tier (T3 denied; T2 needs a click or tap on the right screen)

A spoken "yes" is not an approval for T2: only a click or tap is (CLAUDE.md safety invariants).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from reva_core.policy.registry import DEFAULT_REGISTRY, Registry, Tier

AUTHORIZER_VERSION = "1.0.0"
AMBIGUITY_MARGIN = 0.15
MAX_OPTIONS = 3


class Resolution(StrEnum):
    EXACT = "exact"  # canonical name
    ALIAS = "alias"  # a verified alias the owner approved
    CONFIRMED = "confirmed"  # the owner confirmed this phrase before
    TYPED_VALUE = "typed_value"  # parsed by the normalizer (money, number, date)
    LEXICAL = "lexical"
    FUZZY = "fuzzy"
    VECTOR = "vector"
    NONE = "none"


TRUSTED = frozenset(
    {Resolution.EXACT, Resolution.ALIAS, Resolution.CONFIRMED, Resolution.TYPED_VALUE}
)


@dataclass(frozen=True)
class Entity:
    slot: str
    phrase: str
    resolution: Resolution
    score: float | None = None
    margin: float | None = None  # lead over the runner-up
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    capability: str
    args: Mapping[str, Any]
    entities: tuple[Entity, ...] = ()
    unresolved_terms: tuple[
        str, ...
    ] = ()  # content-bearing words nothing explained (filler removed)
    source: str = "rule"  # rule, planner or ui
    origin_device: str = "local"
    target_device: str = "local"
    hosted_origin: bool = False  # produced by a hosted model: needs the domain's consent


@dataclass(frozen=True)
class Approval:
    proposal_id: str
    args_hash: str
    target_device: str  # the device whose screen the click or tap happened on
    user: str
    via: str  # "click" or "tap" count; "speech" never does
    expires_at: datetime


@dataclass(frozen=True)
class AuthState:
    now: datetime
    approval: Approval | None = None
    user: str = "owner"
    consent: Mapping[str, bool] = field(default_factory=dict)  # hosted-model consent per domain
    device_scopes: frozenset[str] | None = None  # None: local, unrestricted


@dataclass(frozen=True)
class AuthorizationDecision:
    proposal_id: str
    allowed: bool
    reason: str
    tier: str | None = None
    unresolved: tuple[str, ...] = ()
    clarification: dict[str, Any] | None = None
    problems: tuple[str, ...] = ()  # argument problems; for logs and tests, not in the contract
    authorizer_version: str = AUTHORIZER_VERSION

    def to_dict(self) -> dict[str, Any]:
        """The `AuthorizationDecision` of contracts/authorization-decision.schema.json."""
        out: dict[str, Any] = {
            "schema_version": "2.0",
            "proposal_id": self.proposal_id,
            "allowed": self.allowed,
            "reason": self.reason,
            "authorizer_version": self.authorizer_version,
        }
        if self.tier is not None:
            out["tier"] = self.tier
        if self.unresolved:
            out["unresolved"] = list(self.unresolved)
        if self.clarification is not None:
            out["clarification"] = self.clarification
        return out


def canonical_args(args: Mapping[str, Any]) -> str:
    """One spelling for a set of arguments: sorted keys, no spaces, UTF-8 characters kept."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def args_hash(args: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()


def authorize(
    proposal: Proposal, state: AuthState, registry: Registry = DEFAULT_REGISTRY
) -> AuthorizationDecision:
    pid = proposal.proposal_id

    def no(reason: str, tier: Tier | None = None, **extra: Any) -> AuthorizationDecision:
        return AuthorizationDecision(
            pid, False, reason, tier.value if tier is not None else None, **extra
        )

    if registry.is_forbidden(proposal.capability):
        return no("FORBIDDEN_CAPABILITY")
    capability = registry.get(proposal.capability)
    if capability is None:
        return no("UNKNOWN_CAPABILITY")
    tier = capability.tier

    problems = registry.validate_args(capability, proposal.args)
    if problems:
        return no("INVALID_ARGS", tier, problems=tuple(problems))

    for entity in proposal.entities:
        if entity.resolution not in TRUSTED:
            reason = "UNRESOLVED_TERMS" if entity.resolution == Resolution.NONE else "LOW_EVIDENCE"
            return no(
                reason,
                tier,
                unresolved=(entity.phrase,),
                clarification=_clarification(entity),
            )
    if proposal.unresolved_terms:
        return no(
            "UNRESOLVED_TERMS",
            tier,
            unresolved=tuple(proposal.unresolved_terms),
            clarification={"question_template": "unresolved_terms"},
        )
    for entity in proposal.entities:
        if len(entity.candidates) > 1 and (
            entity.margin is None or entity.margin < AMBIGUITY_MARGIN
        ):
            return no(
                "AMBIGUOUS_ENTITY",
                tier,
                unresolved=(entity.phrase,),
                clarification={
                    "question_template": "ambiguous_entity",
                    "options": list(entity.candidates[:MAX_OPTIONS]),
                },
            )

    approval = state.approval
    if approval is not None and not _bound(approval, proposal, state, capability.confirm_on):
        return no("STATE_MISMATCH", tier)

    domain = capability.domain
    if proposal.hosted_origin and domain is not None and not state.consent.get(domain, False):
        return no("CONSENT_REQUIRED", tier)
    if state.device_scopes is not None and not _in_scope(
        capability.device, domain, state.device_scopes
    ):
        return no("CONSENT_REQUIRED", tier)

    if tier == Tier.T3:
        return no("DENIED_TIER", tier)
    if tier == Tier.T2 and (
        approval is None or approval.via not in ("click", "tap") or state.now >= approval.expires_at
    ):
        return no("APPROVAL_REQUIRED", tier)
    return AuthorizationDecision(pid, True, "OK", tier.value)


def _bound(
    approval: Approval, proposal: Proposal, state: AuthState, confirm_on: str | None
) -> bool:
    """An approval counts only for this proposal, these arguments, this user and device."""
    if approval.proposal_id != proposal.proposal_id:
        return False
    if approval.args_hash != args_hash(proposal.args):
        return False
    if approval.user != state.user:
        return False
    expected_device = proposal.target_device if confirm_on == "target" else proposal.origin_device
    return approval.target_device == expected_device


def _in_scope(device: str, domain: str | None, scopes: frozenset[str]) -> bool:
    if domain is not None:
        return domain in scopes
    return device in scopes or "any" in scopes


def _clarification(entity: Entity) -> dict[str, Any]:
    clarification: dict[str, Any] = {"question_template": f"which_{entity.slot}"}
    if entity.candidates:
        clarification["options"] = list(entity.candidates[:MAX_OPTIONS])
    return clarification
