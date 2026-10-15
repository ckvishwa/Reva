"""The capability registry (ARD-600 section 2, ADR-033): the one list of things REVA can be asked.

Loaded from the packaged copy of `contracts/capability-registry.v2.json` (a test keeps the copies
equal). The tier of a capability comes only from here, never from a model, a network hint or an
argument (AR-AGT-003). Names that start with a forbidden prefix (payments, transfers, shell, file
deletion, sending email, ...) are refused by name even though they are not in the registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from reva_core.policy import schema

REGISTRY_PATH = Path(__file__).with_name("data") / "capability-registry.v2.json"


class Tier(StrEnum):
    T0 = "T0"  # information: answered or read, nothing changes
    T1 = "T1"  # safe and reversible: runs without asking
    T2 = "T2"  # sensitive: needs a click or tap approval on the target device
    T3 = "T3"  # high risk: denied


@dataclass(frozen=True)
class Capability:
    name: str
    device: str
    tier: Tier
    confirm_on: str | None  # "origin" or "target" device for T2, else None
    idempotent: bool
    evidence_kind: str
    args_schema: dict[str, Any]

    @property
    def domain(self) -> str | None:
        """The life domain the capability belongs to (`finance`, `health`, ...), if any."""
        prefix = self.name.split(".", 1)[0]
        return prefix if prefix in DOMAINS else None


DOMAINS = frozenset(
    {"memory", "finance", "health", "coach", "career", "learn", "cyber", "personal"}
)


class Registry:
    def __init__(self, document: dict[str, Any]) -> None:
        self.revision = int(document["registry_revision"])
        self.forbidden_prefixes = tuple(document["forbidden_capability_prefixes"])
        self._capabilities: dict[str, Capability] = {}
        for entry in document["capabilities"]:
            schema.check_supported(entry["args_schema"])
            capability = Capability(
                name=entry["capability"],
                device=entry["device"],
                tier=Tier(entry["tier"]),
                confirm_on=entry["confirm_on"],
                idempotent=bool(entry["idempotent"]),
                evidence_kind=entry["evidence_kind"],
                args_schema=entry["args_schema"],
            )
            if capability.name in self._capabilities:
                raise ValueError(f"duplicate capability {capability.name}")
            if self.is_forbidden(capability.name):
                raise ValueError(
                    f"{capability.name} is a forbidden capability and cannot be registered"
                )
            if capability.tier == Tier.T2 and capability.confirm_on not in ("origin", "target"):
                raise ValueError(
                    f"{capability.name}: a T2 capability must say where it is confirmed"
                )
            self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def __contains__(self, name: object) -> bool:
        return name in self._capabilities

    def is_forbidden(self, name: str) -> bool:
        lowered = name.lower()
        return any(lowered.startswith(prefix) for prefix in self.forbidden_prefixes)

    def validate_args(self, capability: Capability, args: Any) -> list[str]:
        if not isinstance(args, dict):
            return ["$: arguments must be an object"]
        return schema.validate(args, capability.args_schema)


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    return Registry(json.loads(path.read_text(encoding="utf-8")))


DEFAULT_REGISTRY = load_registry()
