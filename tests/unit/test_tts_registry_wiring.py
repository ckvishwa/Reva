"""Settings -> registry -> provider wiring for TTS (AR-CORE-003, ADR-040)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.providers.registry import ProviderKind
from reva_core.providers.tts import RegistryTTS, build_tts_registry
from reva_core.shared.errors import ProviderError
from tests.fixtures.kokoro_assets import write_assets
from tests.fixtures.process_utils import wait_until_dead

_FAKE_KOKORO = "tests.fixtures.fake_kokoro_worker"
_FAKE_CHATTERBOX = "tests.fixtures.fake_chatterbox_worker"


def _settings(tmp_path: Path, *, kokoro: bool, chatterbox: bool, tamper: str | None = None):
    values: dict[str, object] = {"data_dir": tmp_path / "data", "tts_enabled": True}
    if kokoro:
        root = tmp_path / "assets"
        write_assets(root, tamper=tamper)
        values.update(
            asset_root=root,
            kokoro_python=Path(sys.executable),
            kokoro_config_asset_id="kokoro.config",
            kokoro_model_asset_id="kokoro.model",
            kokoro_voice_asset_id="kokoro.voice.af_heart",
        )
    if chatterbox:
        reference = tmp_path / "reference.wav"
        reference.write_bytes(b"unused by the fake worker")
        values.update(tts_python=Path(sys.executable), tts_reference_wav=reference)
    return load_settings(_env_file=None, **values)


def _registry(tmp_path: Path, settings):
    return build_tts_registry(
        settings,
        tmp_path / "speech",
        kokoro_worker_module=_FAKE_KOKORO,
        chatterbox_worker_module=_FAKE_CHATTERBOX,
    )


def test_nothing_configured_registers_nothing(tmp_path):
    settings = _settings(tmp_path, kokoro=False, chatterbox=False)

    assert _registry(tmp_path, settings).names(ProviderKind.TTS) == ()


def test_kokoro_is_registered_first_and_default(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=True)

    assert _registry(tmp_path, settings).names(ProviderKind.TTS) == ("kokoro", "chatterbox")


async def test_kokoro_synthesizes_through_the_facade(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=False)
    tts = RegistryTTS(_registry(tmp_path, settings), preferred=settings.tts_provider)
    try:
        audio = await tts.synthesize("Hello there.", "en")
        assert audio.provider == "kokoro_af_heart"
        assert tts.selected_name == "kokoro"
    finally:
        await tts.shutdown()


async def test_tampered_kokoro_falls_back_to_chatterbox_for_synthesis(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=True, tamper="kokoro.model")
    tts = RegistryTTS(_registry(tmp_path, settings), preferred=settings.tts_provider)
    try:
        audio = await tts.synthesize("Hello there.", "en")
        assert audio.provider == "chatterbox_multilingual_worker"
        assert tts.selected_name == "chatterbox"
        assert tts.skipped[0][0] == "kokoro"
    finally:
        await tts.shutdown()


async def test_interruptible_speech_never_falls_back_to_a_provider_that_cannot_stop(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=True, tamper="kokoro.model")
    tts = RegistryTTS(_registry(tmp_path, settings), preferred=settings.tts_provider)
    try:
        with pytest.raises(ProviderError):
            await tts.require_interruptible()
    finally:
        await tts.shutdown()


async def test_shutdown_stops_the_selected_worker(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=False)
    tts = RegistryTTS(_registry(tmp_path, settings), preferred=settings.tts_provider)
    await tts.synthesize("Hello.", "en")
    pid = tts.selected_provider.worker_pid
    assert pid is not None

    await tts.shutdown()

    assert wait_until_dead(pid, 3.0)


def test_lifecycle_exposes_the_registry_backed_provider(tmp_path):
    settings = _settings(tmp_path, kokoro=True, chatterbox=False)
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    try:
        assert isinstance(lifecycle.text_to_speech_provider, RegistryTTS)
    finally:
        lifecycle.shutdown()


def test_lifecycle_has_no_tts_when_disabled(tmp_path):
    settings = load_settings(_env_file=None, data_dir=tmp_path / "data")
    lifecycle = CoreLifecycle(settings)
    lifecycle.startup()
    try:
        assert lifecycle.text_to_speech_provider is None
    finally:
        lifecycle.shutdown()


async def test_an_existing_chatterbox_only_setup_keeps_speaking_without_kokoro(tmp_path):
    """Settings compatibility: no Kokoro paths configured, only the earlier Chatterbox ones."""
    settings = _settings(tmp_path, kokoro=False, chatterbox=True)
    registry = _registry(tmp_path, settings)
    assert registry.names(ProviderKind.TTS) == ("chatterbox",)

    selection = await registry.acquire(
        ProviderKind.TTS, preferred=settings.tts_provider, require=frozenset({"synthesize"})
    )

    assert settings.tts_provider == "kokoro"  # the new default does not strand old setups
    assert selection.name == "chatterbox"
    await selection.provider.shutdown()
