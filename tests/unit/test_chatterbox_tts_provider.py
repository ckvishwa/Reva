from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

from reva_core.models.chatterbox_tts import ChatterboxWorkerTTSProvider, _read_wav_metadata
from reva_core.shared.errors import ProviderError, ProviderErrorKind, ValidationError


def _provider(tmp_path: Path) -> ChatterboxWorkerTTSProvider:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"not used by fake worker")
    return ChatterboxWorkerTTSProvider(
        python_exe=Path(sys.executable),
        reference_wav=reference,
        model_id="fake-model",
        device="cpu",
        output_dir=tmp_path / "speech",
        ready_timeout_seconds=5.0,
        synthesis_timeout_seconds=5.0,
        worker_module="tests.fixtures.fake_chatterbox_worker",
    )


async def test_chatterbox_worker_provider_synthesizes_valid_wav(tmp_path):
    provider = _provider(tmp_path)
    try:
        result = await provider.synthesize("Good morning.", "en")
    finally:
        await provider.shutdown()

    assert result.path.is_file()
    assert result.sample_rate == 24_000
    assert result.duration_ms > 0
    assert result.language == "en"
    assert result.provider == "chatterbox_multilingual_worker"


async def test_chatterbox_worker_provider_supports_telugu_language(tmp_path):
    provider = _provider(tmp_path)
    try:
        result = await provider.synthesize("శుభోదయం.", "te")
    finally:
        await provider.shutdown()

    assert result.path.is_file()
    assert result.language == "te"


async def test_chatterbox_worker_provider_rejects_unsupported_language(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ValidationError):
            await provider.synthesize("Bonjour.", "fr")
    finally:
        await provider.shutdown()


async def test_chatterbox_worker_provider_rejects_overlong_text(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ValidationError):
            await provider.synthesize("x" * 801, "en")
    finally:
        await provider.shutdown()


async def test_chatterbox_worker_provider_rejects_worker_path_escape(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ProviderError) as excinfo:
            await provider.synthesize("outside", "en")
    finally:
        await provider.shutdown()

    assert excinfo.value.kind == ProviderErrorKind.INVALID_RESPONSE


async def test_chatterbox_worker_provider_restarts_once_after_crash(tmp_path):
    provider = _provider(tmp_path)
    try:
        result = await provider.synthesize("crash-once", "en")
    finally:
        await provider.shutdown()

    assert result.path.is_file()
    assert (tmp_path / "speech" / "crash-once-marker").is_file()


async def test_chatterbox_worker_provider_maps_worker_error_to_unavailable(tmp_path):
    provider = _provider(tmp_path)
    try:
        with pytest.raises(ProviderError) as excinfo:
            await provider.synthesize("worker-error", "en")
    finally:
        await provider.shutdown()

    assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE


def test_wav_metadata_accepts_ieee_float_wav(tmp_path):
    path = tmp_path / "float.wav"
    sample_rate = 24_000
    channels = 1
    bits_per_sample = 32
    block_align = channels * bits_per_sample // 8
    data = struct.pack("<ff", 0.0, 0.25)
    fmt = struct.pack(
        "<HHIIHH",
        3,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        bits_per_sample,
    )
    path.write_bytes(
        b"RIFF"
        + struct.pack("<I", 4 + (8 + len(fmt)) + (8 + len(data)))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )

    assert _read_wav_metadata(path) == (sample_rate, 2.0)
