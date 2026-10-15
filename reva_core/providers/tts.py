"""TTS wiring: settings -> registry, and a lazy facade Core can hold at startup.

Selecting a provider means verifying and loading a voice, which can take
seconds. The facade defers that to first use so Core becomes healthy
immediately, and so a refused voice falls back at the moment it matters.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

from reva_core.config.settings import Settings
from reva_core.models.chatterbox_tts import ChatterboxWorkerTTSProvider
from reva_core.models.tts import SynthesizedAudio
from reva_core.providers.registry import (
    ProviderKind,
    ProviderRegistry,
    ProviderSelection,
    ProviderSpec,
)
from reva_core.shared.errors import ProviderError
from reva_core.shared.logging import get_logger
from reva_core.voice.kokoro_provider import KokoroAssetIds, KokoroSpeechProvider

logger = get_logger("providers.tts")

_SYNTHESIZE = frozenset({"synthesize"})
_INTERRUPTIBLE = frozenset({"speak", "stop"})


def build_tts_registry(
    settings: Settings,
    output_dir: Path,
    *,
    kokoro_worker_module: str = "reva_core.voice.kokoro_worker",
    chatterbox_worker_module: str = "reva_core.voice.chatterbox_worker",
) -> ProviderRegistry:
    """Register every TTS provider the settings configure. Kokoro first."""
    registry = ProviderRegistry()
    manifest = settings.asset_manifest_path

    if settings.kokoro_python is not None and settings.asset_root is not None and manifest:
        kokoro_python = settings.kokoro_python
        asset_root = settings.asset_root
        asset_ids = KokoroAssetIds(
            config=settings.kokoro_config_asset_id,
            model=settings.kokoro_model_asset_id,
            voice=settings.kokoro_voice_asset_id,
        )
        registry.register(
            ProviderSpec(
                kind=ProviderKind.TTS,
                name="kokoro",
                factory=(
                    lambda: KokoroSpeechProvider(
                        python_exe=kokoro_python,
                        manifest_path=manifest,
                        asset_root=asset_root,
                        asset_ids=asset_ids,
                        output_dir=output_dir,
                        voice=settings.kokoro_voice,
                        device=settings.kokoro_device,
                        worker_module=kokoro_worker_module,
                        ready_timeout_seconds=settings.tts_ready_timeout_seconds,
                        stop_ack_timeout_seconds=settings.tts_stop_ack_timeout_seconds,
                    )
                ),
                capabilities=_SYNTHESIZE | _INTERRUPTIBLE,
                default=True,
            )
        )

    if settings.tts_python is not None and settings.tts_reference_wav is not None:
        chatterbox_python = settings.tts_python
        reference = settings.tts_reference_wav
        registry.register(
            ProviderSpec(
                kind=ProviderKind.TTS,
                name="chatterbox",
                factory=(
                    lambda: ChatterboxWorkerTTSProvider(
                        python_exe=chatterbox_python,
                        reference_wav=reference,
                        model_id=settings.tts_model_id,
                        device=settings.tts_device,
                        output_dir=output_dir,
                        default_language=settings.tts_default_language,
                        ready_timeout_seconds=settings.tts_ready_timeout_seconds,
                        synthesis_timeout_seconds=settings.tts_synthesis_timeout_seconds,
                        worker_module=chatterbox_worker_module,
                    )
                ),
                # Chatterbox cannot be interrupted mid-synthesis, so it is never
                # offered for sessions that need stop (AR-VA-008).
                capabilities=_SYNTHESIZE,
                default=settings.tts_provider == "chatterbox",
            )
        )
    return registry


def _accepts_speed(function: Any) -> bool:
    try:
        return "speed" in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False


class RegistryTTS:
    """Core-facing TTS: resolves a provider on first use, falls back on refusal."""

    def __init__(self, registry: ProviderRegistry, *, preferred: str) -> None:
        self._registry = registry
        self._preferred = preferred
        self._lock = asyncio.Lock()
        self._last: ProviderSelection | None = None

    @property
    def selected_name(self) -> str | None:
        return self._last.name if self._last is not None else None

    @property
    def selected_provider(self) -> Any:
        return self._last.provider if self._last is not None else None

    @property
    def skipped(self) -> tuple[tuple[str, str], ...]:
        return self._last.skipped if self._last is not None else ()

    async def synthesize(
        self, text: str, language: str, *, speed: float | None = None
    ) -> SynthesizedAudio:
        selection = await self._select(_SYNTHESIZE)
        provider = selection.provider
        if speed is not None and _accepts_speed(provider.synthesize):
            audio: SynthesizedAudio = await provider.synthesize(text, language, speed=speed)
        else:
            audio = await provider.synthesize(text, language)
        return audio

    async def require_interruptible(self) -> Any:
        """A provider that supports speak + stop, or `ProviderError`."""
        return (await self._select(_INTERRUPTIBLE)).provider

    async def warm(self) -> bool:
        """Load the preferred voice now (manifest check, worker start, model load).

        True when a voice is ready. A voice that cannot load (missing or tampered assets, no
        interpreter) is logged by reason and reported as False, never raised: speaking later
        will try again and fall back as usual.
        """
        try:
            provider = await self.require_interruptible()
            await provider.health()
        except ProviderError as exc:
            logger.warning("tts warm-up skipped: %s", exc.kind.value)
            return False
        return True

    async def stop(self, *, turn_epoch: int, scope: str = "") -> None:
        """Silence every provider already in use. Never loads one just to stop it."""
        for provider in self._registry.instances(ProviderKind.TTS):
            stop = getattr(provider, "stop", None)
            if stop is not None:
                await stop(turn_epoch=turn_epoch, scope=scope)

    async def shutdown(self) -> None:
        for provider in self._registry.instances(ProviderKind.TTS):
            shutdown = getattr(provider, "shutdown", None)
            if shutdown is not None:
                await shutdown()

    async def _select(self, require: frozenset[str]) -> ProviderSelection:
        async with self._lock:
            selection = await self._registry.acquire(
                ProviderKind.TTS, preferred=self._preferred, require=require
            )
            for name, reason in selection.skipped:
                logger.warning("tts provider %s skipped: %s", name, reason)
            self._last = selection
            return selection
