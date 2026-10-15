"""B2.3: the mood's speaking rate reaches the voice, clamped, and only providers that take it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from reva_core.models.tts import SynthesizedAudio
from reva_core.providers.registry import ProviderKind, ProviderRegistry, ProviderSpec
from reva_core.providers.tts import RegistryTTS
from reva_core.voice.kokoro_provider import MAX_SPEED, MIN_SPEED, clamp_speed
from reva_core.voice.kokoro_worker import _requested_speed


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, 1.0),
        (float("nan"), 1.0),
        (0.1, MIN_SPEED),
        (9.0, MAX_SPEED),
        (0.95, 0.95),
        (1.1, 1.1),
    ],
)
def test_the_speed_is_clamped_to_a_natural_range(given: float | None, expected: float) -> None:
    assert clamp_speed(given) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({}, 1.0),
        ({"speed": "fast"}, 1.0),
        ({"speed": None}, 1.0),
        ({"speed": 5}, 1.2),
        ({"speed": 0.2}, 0.8),
        ({"speed": 0.9}, 0.9),
    ],
)
def test_the_worker_trusts_nothing_about_the_requested_speed(raw: dict, expected: float) -> None:
    assert _requested_speed(raw) == expected


def _audio(tmp_path: Path) -> SynthesizedAudio:
    return SynthesizedAudio(
        path=tmp_path / "a.wav", sample_rate=24000, duration_ms=10, provider="x", language="en"
    )


async def _registry_with(provider: object) -> RegistryTTS:
    registry = ProviderRegistry()
    registry.register(
        ProviderSpec(
            kind=ProviderKind.TTS,
            name="fake",
            factory=lambda: provider,
            capabilities=frozenset({"synthesize"}),
        )
    )
    return RegistryTTS(registry, preferred="fake")


async def test_a_provider_that_takes_speed_gets_it(tmp_path: Path) -> None:
    seen: list[float | None] = []

    async def synthesize(
        text: str, language: str, *, speed: float | None = None
    ) -> SynthesizedAudio:
        seen.append(speed)
        return _audio(tmp_path)

    tts = await _registry_with(SimpleNamespace(synthesize=synthesize))

    await tts.synthesize("hi", "en", speed=0.95)
    await tts.synthesize("hi", "en")

    assert seen == [0.95, None]


async def test_a_provider_without_speed_is_called_the_old_way(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    async def synthesize(text: str, language: str) -> SynthesizedAudio:
        calls.append((text, language))
        return _audio(tmp_path)

    tts = await _registry_with(SimpleNamespace(synthesize=synthesize))

    await tts.synthesize("hi", "en", speed=1.05)

    assert calls == [("hi", "en")]
