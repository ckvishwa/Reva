from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

from reva_core.models.chatterbox_tts import ChatterboxWorkerTTSProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("REVA_RUN_REAL_VOICE_TESTS") != "1",
    reason="real Chatterbox voice tests are opt-in",
)


def _required_path_env(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required for real Chatterbox voice tests")
    path = Path(value)
    if not path.exists():
        pytest.skip(f"{name} does not exist")
    return path


@pytest.mark.asyncio
async def test_real_chatterbox_provider_synthesizes_english_wav(tmp_path):
    python_exe = _required_path_env("REVA_TTS_PYTHON")
    reference_wav = _required_path_env("REVA_TTS_REFERENCE_WAV")
    provider = ChatterboxWorkerTTSProvider(
        python_exe=python_exe,
        reference_wav=reference_wav,
        model_id=os.environ.get("REVA_TTS_MODEL_ID", "shankarpandala/chatterbox-telugu"),
        device=os.environ.get("REVA_TTS_DEVICE", "cuda"),
        output_dir=tmp_path / "speech",
        ready_timeout_seconds=float(os.environ.get("REVA_REAL_TTS_READY_TIMEOUT", "180")),
        synthesis_timeout_seconds=float(os.environ.get("REVA_REAL_TTS_TIMEOUT", "180")),
    )
    try:
        audio = await provider.synthesize("Good morning.", "en")

        assert audio.sample_rate == 24_000
        assert audio.duration_ms > 0
        assert audio.path.exists()
        with wave.open(str(audio.path), "rb") as wav:
            assert wav.getframerate() == 24_000
            assert wav.getnframes() > 0
    finally:
        await provider.shutdown()
