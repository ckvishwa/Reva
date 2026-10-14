"""A session interrupt must reach the TTS provider that is actually speaking."""

from __future__ import annotations

import sys
from pathlib import Path

from reva_core.config.settings import load_settings
from reva_core.providers.tts import RegistryTTS, build_tts_registry
from tests.fixtures.kokoro_assets import write_assets


def _tts(tmp_path: Path) -> RegistryTTS:
    root = tmp_path / "assets"
    write_assets(root)
    settings = load_settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        tts_enabled=True,
        asset_root=root,
        kokoro_python=Path(sys.executable),
        kokoro_config_asset_id="kokoro.config",
        kokoro_model_asset_id="kokoro.model",
        kokoro_voice_asset_id="kokoro.voice.af_heart",
    )
    registry = build_tts_registry(
        settings, tmp_path / "speech", kokoro_worker_module="tests.fixtures.fake_kokoro_worker"
    )
    return RegistryTTS(registry, preferred="kokoro")


async def test_stop_before_any_provider_is_loaded_does_nothing(tmp_path):
    tts = _tts(tmp_path)

    await tts.stop(turn_epoch=3)

    assert tts.selected_provider is None


async def test_stop_invalidates_older_epochs_on_the_active_provider(tmp_path):
    tts = _tts(tmp_path)
    try:
        await tts.synthesize("Hello.", "en")
        provider = tts.selected_provider

        await tts.stop(turn_epoch=3)
        chunks = [c async for c in provider.speak("Stale.", language="en", turn_epoch=2)]
        fresh = [c async for c in provider.speak("Fresh.", language="en", turn_epoch=3)]
    finally:
        await tts.shutdown()

    assert chunks == []
    assert len(fresh) == 3
