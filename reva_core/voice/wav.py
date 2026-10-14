"""Small, dependency-free WAV helpers shared by the TTS providers."""

from __future__ import annotations

import struct
import wave
from collections.abc import Sequence
from pathlib import Path

from reva_core.shared.errors import ProviderError, ProviderErrorKind


def read_wav_metadata(path: Path) -> tuple[int, float]:
    """Return `(sample_rate, frame_count)` for a PCM or float WAV."""
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")

    offset = 12
    sample_rate = 0
    block_align = 0
    data_size = 0
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > len(data):
            raise ValueError("WAV chunk exceeds file size")
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ValueError("WAV fmt chunk is too small")
            audio_format, _, sample_rate, _, block_align, _ = struct.unpack_from(
                "<HHIIHH", data, chunk_start
            )
            if audio_format not in {1, 3, 65534}:
                raise ValueError("unsupported WAV sample format")
        elif chunk_id == b"data":
            data_size = chunk_size
        offset = chunk_end + (chunk_size % 2)

    if sample_rate <= 0 or block_align <= 0 or data_size <= 0:
        raise ValueError("WAV metadata is incomplete")
    return sample_rate, data_size / block_align


def validate_under_directory(path: Path, directory: Path) -> Path:
    """Resolve `path` and require it to live inside `directory`."""
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(directory.resolve())
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker returned path outside output dir"
        ) from exc
    return resolved_path


def validate_wav(path: Path, *, expected_sample_rate: int) -> tuple[int, int]:
    """Return `(sample_rate, duration_ms)` or raise `ProviderError(INVALID_RESPONSE)`."""
    if not path.is_file():
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker output file missing")
    try:
        sample_rate, frames = read_wav_metadata(path)
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker output is not WAV"
        ) from exc
    if sample_rate != expected_sample_rate:
        raise ProviderError(
            ProviderErrorKind.INVALID_RESPONSE, "TTS worker WAV sample rate invalid"
        )
    if frames <= 0:
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker WAV has no audio")
    return sample_rate, int((frames / sample_rate) * 1000)


def join_wavs(parts: Sequence[Path], destination: Path) -> tuple[int, int]:
    """Concatenate same-format PCM WAV files. Returns `(sample_rate, duration_ms)`."""
    if not parts:
        raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "no audio chunks to join")
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames_total = 0
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(destination), "wb") as out:
        out.setparams(params)
        for part in parts:
            with wave.open(str(part), "rb") as source:
                if source.getparams()[:3] != params[:3] or source.getframerate() != params[2]:
                    raise ProviderError(
                        ProviderErrorKind.INVALID_RESPONSE, "TTS chunks have mismatched formats"
                    )
                frames = source.readframes(source.getnframes())
                out.writeframes(frames)
                frames_total += source.getnframes()
    return params[2], int((frames_total / params[2]) * 1000)
