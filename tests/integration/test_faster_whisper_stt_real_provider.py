from __future__ import annotations

import os
from pathlib import Path

import pytest

from reva_core.models.faster_whisper_stt import FasterWhisperSTTProvider
from reva_core.models.stt import TranscriptionInput

pytestmark = pytest.mark.skipif(
    os.environ.get("REVA_RUN_REAL_VOICE_TESTS") != "1",
    reason="real faster-whisper tests are opt-in",
)


def _required_audio_fixture() -> Path:
    value = os.environ.get("REVA_REAL_STT_AUDIO_WAV")
    if not value:
        pytest.skip("REVA_REAL_STT_AUDIO_WAV is required for real faster-whisper tests")
    path = Path(value)
    if not path.exists():
        pytest.skip("REVA_REAL_STT_AUDIO_WAV does not exist")
    return path


@pytest.mark.asyncio
async def test_real_faster_whisper_provider_transcribes_wav():
    provider = FasterWhisperSTTProvider(
        model=os.environ.get("REVA_STT_MODEL", "Systran/faster-whisper-small"),
        device=os.environ.get("REVA_STT_DEVICE", "cpu"),
        compute_type=os.environ.get("REVA_STT_COMPUTE_TYPE", "int8"),
        timeout_seconds=float(os.environ.get("REVA_REAL_STT_TIMEOUT", "120")),
    )

    result = await provider.transcribe(
        TranscriptionInput(path=_required_audio_fixture(), media_type="audio/wav")
    )

    assert result.text.strip()
    assert result.language in {"en", "te"}
    assert result.duration_ms > 0
