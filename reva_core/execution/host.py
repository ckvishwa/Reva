"""Run a registered capability only from a valid, single-use REVA execution order.

This boundary is shared by future shell, browser, plugin and node handlers. It does not expose
model-authored tool text as execution authority; the Broker must first issue a signed grant.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reva_core.policy.authorize import args_hash
from reva_core.policy.broker import ExecutionOrder
from reva_core.policy.grants import GrantVerifier
from reva_core.policy.registry import Registry, Tier

ToolHandler = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]
EvidenceVerifier = Callable[[Mapping[str, str]], bool]


@dataclass(frozen=True)
class ToolResult:
    status: str
    reason: str
    evidence: dict[str, str] | None = None


@dataclass
class ToolHost:
    verifier: GrantVerifier
    registry: Registry
    target_device: str
    actor: str = "owner"
    evidence_verifiers: Mapping[str, EvidenceVerifier] = field(default_factory=dict)
    _handlers: dict[str, ToolHandler] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def register(
        self,
        capability: str,
        handler: ToolHandler,
    ) -> None:
        definition = self.registry.get(capability)
        if definition is None or definition.tier in (Tier.T0, Tier.T3):
            raise ValueError("capability is not executable")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            if capability in self._handlers:
                raise ValueError("capability already registered")
            self._handlers[capability] = handler

    def execute(self, order: ExecutionOrder, *, now: datetime) -> ToolResult:
        with self._lock:
            definition = self.registry.get(order.capability)
            handler = self._handlers.get(order.capability)
            if definition is None or definition.tier in (Tier.T0, Tier.T3) or handler is None:
                return ToolResult("denied", "NO_HANDLER")
            if order.target_device != self.target_device:
                return ToolResult("denied", "WRONG_TARGET")
            # Freeze the exact arguments that the signed hash and handler will see.
            args = dict(order.args)
            problems = self.registry.validate_args(definition, args)
            if problems:
                return ToolResult("denied", "INVALID_ARGS")
            check = self.verifier.verify(
                order.grant,
                order.signature,
                now=now,
                capability=order.capability,
                args_hash=args_hash(args),
                target_device=self.target_device,
                actor=self.actor,
            )
            if not check.ok:
                return ToolResult("denied", check.reason)
            try:
                evidence = handler(args)
            except Exception:  # noqa: BLE001 - one tool failure cannot escape the execution boundary
                return ToolResult("failed", "HANDLER_FAILED")
            if not isinstance(evidence, Mapping):
                return ToolResult("unknown", "MISSING_EVIDENCE")
            kind = evidence.get("kind")
            ref = evidence.get("ref")
            if (
                kind != definition.evidence_kind
                or not isinstance(ref, str)
                or not (0 < len(ref) <= 200)
            ):
                return ToolResult("unknown", "EVIDENCE_MISMATCH")
            accepted = {"kind": kind, "ref": ref}
            evidence_verifier = self.evidence_verifiers.get(order.capability)
            if evidence_verifier is None:
                return ToolResult("observed", "UNVERIFIED_EVIDENCE", accepted)
            try:
                verified = evidence_verifier(accepted)
            except Exception:  # noqa: BLE001 - a broken verifier cannot grant success
                verified = False
            if verified is not True:
                return ToolResult("unknown", "EVIDENCE_NOT_VERIFIED")
            return ToolResult("verified", "OK", accepted)
