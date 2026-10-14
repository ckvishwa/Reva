"""Capability-driven provider registry (ARD-300 §5, AR-CORE-003).

Selection order is: the caller's preference, then the default, then
registration order. A candidate is skipped, with its reason recorded,
when it lacks a required capability, refuses to build (for example a
failed asset check), or reports itself unhealthy. If nothing remains the
registry raises `ProviderError(UNAVAILABLE)` rather than quietly picking
a fake. A deterministic provider is only ever returned when the caller
asks for it by name or passes `allow_deterministic=True` (ADR-019).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.shared.logging import get_logger

logger = get_logger("providers.registry")


class ProviderKind(StrEnum):
    REASONING = "reasoning"
    STT = "stt"
    TTS = "tts"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class ProviderSpec:
    kind: ProviderKind
    name: str
    factory: Callable[[], Any]
    capabilities: frozenset[str]
    default: bool = False
    deterministic: bool = False


@dataclass(frozen=True)
class ProviderSelection:
    kind: ProviderKind
    name: str
    provider: Any
    skipped: tuple[tuple[str, str], ...]


class ProviderRegistry:
    def __init__(self) -> None:
        self._specs: list[ProviderSpec] = []
        self._instances: dict[tuple[ProviderKind, str], Any] = {}

    def register(self, spec: ProviderSpec) -> None:
        if any(s.kind == spec.kind and s.name == spec.name for s in self._specs):
            raise ValueError(f"provider {spec.kind.value}/{spec.name} already registered")
        self._specs.append(spec)

    def names(self, kind: ProviderKind) -> tuple[str, ...]:
        return tuple(s.name for s in self._specs if s.kind == kind)

    def instances(self, kind: ProviderKind) -> tuple[Any, ...]:
        """Providers this registry has successfully acquired (for shutdown)."""
        return tuple(p for (k, _), p in self._instances.items() if k == kind)

    async def acquire(
        self,
        kind: ProviderKind,
        *,
        preferred: str | None = None,
        require: frozenset[str] = frozenset(),
        allow_deterministic: bool = False,
    ) -> ProviderSelection:
        skipped: list[tuple[str, str]] = []
        for spec in self._candidates(kind, preferred):
            if spec.deterministic and not allow_deterministic and spec.name != preferred:
                skipped.append((spec.name, "deterministic provider not allowed"))
                continue
            if not require <= spec.capabilities:
                missing = ",".join(sorted(require - spec.capabilities))
                skipped.append((spec.name, f"missing capability: {missing}"))
                continue
            provider, reason = await self._build(spec)
            if provider is None:
                skipped.append((spec.name, reason))
                continue
            return ProviderSelection(kind, spec.name, provider, tuple(skipped))
        detail = "; ".join(f"{name}: {why}" for name, why in skipped) or "none registered"
        raise ProviderError(
            ProviderErrorKind.UNAVAILABLE, f"no usable {kind.value} provider ({detail})"
        )

    def _candidates(self, kind: ProviderKind, preferred: str | None) -> list[ProviderSpec]:
        specs = [s for s in self._specs if s.kind == kind]
        specs.sort(
            key=lambda s: (
                0 if s.name == preferred else 1,
                0 if s.default else 1,
            )
        )
        return specs

    async def _build(self, spec: ProviderSpec) -> tuple[Any | None, str]:
        key = (spec.kind, spec.name)
        try:
            provider = self._instances.get(key) or spec.factory()
        except ProviderError as exc:
            return None, str(exc)
        try:
            healthy = await _is_healthy(provider)
        except ProviderError as exc:
            self._instances.pop(key, None)
            await _shutdown_quietly(provider)
            return None, str(exc)
        if not healthy:
            self._instances.pop(key, None)
            await _shutdown_quietly(provider)
            return None, "unhealthy"
        self._instances[key] = provider
        return provider, ""


async def _is_healthy(provider: Any) -> bool:
    health = getattr(provider, "health", None)
    if health is None:
        return True
    result = await health()
    return bool(getattr(result, "ok", result))


async def _shutdown_quietly(provider: Any) -> None:
    shutdown = getattr(provider, "shutdown", None)
    if shutdown is None:
        return
    try:
        await shutdown()
    except Exception:
        logger.warning("provider shutdown failed after being skipped", exc_info=True)
