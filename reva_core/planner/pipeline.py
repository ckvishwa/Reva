"""The model proposes; the registry, policy, and executor decide."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from jsonschema import Draft202012Validator

_CONTRACTS = Path(__file__).resolve().parent / "contracts"
_LOGGER = logging.getLogger(__name__)
JsonDict = dict[str, Any]
Registry = dict[str, JsonDict]
_UNAVAILABLE = "I can't answer that right now."
_ACTION_SUCCESS = re.compile(
    r"\b(?:i\s+(?:have\s+)?(?:opened|launched|started|closed|saved|sent|deleted|changed)"
    r"|(?:is|has been|was)\s+(?:now\s+)?(?:opened|closed|saved|sent|deleted)"
    r"|done|all set|successfully)\b",
    re.IGNORECASE,
)
_ACTION_REQUEST = re.compile(
    r"\b(?:open|launch|start|close|save|send|delete|change)\b", re.IGNORECASE
)


class DecisionProvider(Protocol):
    async def decide(self, *, transcript: str, capabilities: list[JsonDict]) -> str: ...


class ActionExecutor(Protocol):
    async def execute(
        self, tool: JsonDict, decision: AuthorizationDecision
    ) -> ExecutionEvidence: ...


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    tier: str


@dataclass(frozen=True)
class ExecutionEvidence:
    status: str
    message: str


class _UnavailableExecutor:
    async def execute(self, tool: JsonDict, decision: AuthorizationDecision) -> ExecutionEvidence:
        return ExecutionEvidence("unknown", "")


def load_registry() -> Registry:
    document = cast(
        JsonDict,
        json.loads((_CONTRACTS / "capability-registry.v2.json").read_text(encoding="utf-8")),
    )
    entries = cast(list[JsonDict], document["capabilities"])
    return {str(entry["capability"]): entry for entry in entries}


def authorize(tool: JsonDict, registry: Registry) -> AuthorizationDecision:
    """Model-supplied risk hints are never consulted."""
    capability_id = tool.get("capability_id")
    entry = registry.get(capability_id) if isinstance(capability_id, str) else None
    if entry is None:
        return AuthorizationDecision(False, "unknown")
    tier = str(entry["tier"])
    return AuthorizationDecision(tier in {"T0", "T1"}, tier)


def validate_decision(raw: str, registry: Registry) -> JsonDict:
    if len(raw) > 16_384:
        raise ValueError("planner response too large")
    try:
        proposal = cast(JsonDict, json.loads(raw))
        schema = json.loads(
            (_CONTRACTS / "planner-decision.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(proposal)
        tools = (
            [proposal["tool"]]
            if proposal["kind"] == "propose_action"
            else proposal["steps"]
            if proposal["kind"] == "propose_plan"
            else []
        )
        if len(tools) > 2:
            raise ValueError("planner step limit")
        for tool in tools:
            entry = registry.get(tool["capability_id"])
            if entry is None:
                raise ValueError("unregistered capability")
            Draft202012Validator(entry["args_schema"]).validate(tool["args"])
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid planner decision") from exc
    except Exception as exc:
        # jsonschema's ValidationError is intentionally reduced to a safe error.
        raise ValueError("invalid planner decision") from exc
    return proposal


class PlannerPipeline:
    def __init__(
        self,
        *,
        local: DecisionProvider,
        cloud: DecisionProvider | None,
        cloud_enabled: Callable[[], bool],
        registry: Registry | None = None,
        executor: ActionExecutor | None = None,
        provider_timeout_seconds: float = 30.0,
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._cloud_enabled = cloud_enabled
        self._registry = registry if registry is not None else load_registry()
        self._executor = executor if executor is not None else _UnavailableExecutor()
        self._provider_timeout_seconds = provider_timeout_seconds

    async def respond(self, transcript: str, **_private_context: object) -> str:
        # This is the consent filter: only these two values cross either
        # provider boundary. The private context is deliberately discarded.
        capabilities = [
            {"capability_id": name, "args_schema": entry["args_schema"]}
            for name, entry in self._registry.items()
        ]
        providers = [self._local]
        if self._cloud_enabled() and self._cloud is not None:
            providers.insert(0, self._cloud)
        for provider in providers:
            try:
                raw = await asyncio.wait_for(
                    provider.decide(transcript=transcript, capabilities=capabilities),
                    timeout=self._provider_timeout_seconds,
                )
                proposal = validate_decision(raw, self._registry)
            except Exception:
                # Provider exceptions can contain request headers. Never log them.
                _LOGGER.warning("planner provider unavailable or invalid")
                continue
            kind = proposal["kind"]
            if kind == "answer":
                if _ACTION_REQUEST.search(transcript) and _ACTION_SUCCESS.search(proposal["text"]):
                    return _UNAVAILABLE
                return str(proposal["text"])
            if kind == "clarify":
                return str(proposal["question"])
            tools = [proposal["tool"]] if kind == "propose_action" else proposal["steps"]
            for tool in tools:
                decision = authorize(tool, self._registry)
                if not decision.allowed:
                    return _UNAVAILABLE
                try:
                    evidence = await self._executor.execute(tool, decision)
                except Exception:
                    return _UNAVAILABLE
                if evidence.status != "verified":
                    return _UNAVAILABLE
            return evidence.message
        return _UNAVAILABLE
